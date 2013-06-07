import os
import time
import errno
import pprint
import struct

from iotop.netlink import Connection, NETLINK_GENERIC, U32Attr, NLM_F_REQUEST
from iotop.genetlink import Controller, GeNlMessage


class DumpableObject(object):
    """Base class for objects that allows easy introspection when printed"""
    def __repr__(self):
        return '%s: %s>' % (str(type(self))[:-1],
                            pprint.pformat(self.__dict__))


#
# Interesting fields in a taskstats output
#

class Stats(DumpableObject):
    members_offsets = [
        ('blkio_delay_total', 40),
        ('swapin_delay_total', 56),
        ('read_bytes', 248),
        ('write_bytes', 256),
        ('cancelled_write_bytes', 264)
    ]

    has_blkio_delay_total = False

    def __init__(self, task_stats_buffer):
        sd = self.__dict__
        for name, offset in Stats.members_offsets:
            data = task_stats_buffer[offset:offset + 8]
            sd[name] = struct.unpack('Q', data)[0]

        # This is a heuristic to detect if CONFIG_TASK_DELAY_ACCT is enabled in
        # the kernel.
        if not Stats.has_blkio_delay_total:
            Stats.has_blkio_delay_total = self.blkio_delay_total != 0

    def accumulate(self, other_stats, destination, coeff=1):
        """Update destination from operator(self, other_stats)"""
        dd = destination.__dict__
        sd = self.__dict__
        od = other_stats.__dict__
        for member, offset in Stats.members_offsets:
            dd[member] = sd[member] + coeff * od[member]

    def delta(self, other_stats, destination):
        """Update destination with self - other_stats"""
        return self.accumulate(other_stats, destination, coeff=-1)

    def is_all_zero(self):
        sd = self.__dict__
        for name, offset in Stats.members_offsets:
            if sd[name] != 0:
                return False
        return True

    @staticmethod
    def build_all_zero():
        stats = Stats.__new__(Stats)
        std = stats.__dict__
        for name, offset in Stats.members_offsets:
            std[name] = 0
        return stats

#
# Netlink usage for taskstats
#

TASKSTATS_CMD_GET = 1
TASKSTATS_CMD_ATTR_PID = 1
TASKSTATS_CMD_ATTR_TGID = 2
TASKSTATS_CMD_ATTR_REGISTER_CPUMASK = 3
TASKSTATS_CMD_ATTR_DEREGISTER_CPUMASK = 4

TASKSTATS_TYPE_PID = 1
TASKSTATS_TYPE_TGID= 2
TASKSTATS_TYPE_STATS = 3
TASKSTATS_TYPE_AGGR_PID = 4
TASKSTATS_TYPE_AGGR_TGID= 5


class TaskStatHelper(object):
    connection = Connection(NETLINK_GENERIC)
    controller = Controller(connection)
    family_id = controller.get_family_id('TASKSTATS')




"""
The taskstats document in (https://www.kernel.org/doc/Documentation/accounting/taskstats.txt)
says that we can get accounting about the thread group using TASKSTATS_CMD_ATTR_TGID instead of
TASKSTATS_CMD_ATTR_PID.
but when i test it, found that it does not including I/O accounting,that is read_bytes&write_bytes
are all zero, not the sum of each thread's read_bytes&write_bytes

so i have to make sum of each thread's account in the thread group in user space:(
    
"""

class TaskCounter(object):
    def __init__(self, tid):
        self._tid = tid
        self._request = GeNlMessage(TaskStatHelper.family_id, cmd=TASKSTATS_CMD_GET,
                           attrs=[U32Attr(TASKSTATS_CMD_ATTR_PID, self._tid)],
                           flags=NLM_F_REQUEST)
        self._stats_total = None
        self._stats_delta = Stats.build_all_zero()
        self.duration = None
        self._timestamp = time.time()

    def _update_stats(self, stats):
        if not self._stats_total:
            self._stats_total = stats
        stats.delta(self._stats_total, self._stats_delta)
        self._stats_total = stats

    def update_task_stats(self):
        t0 = time.time()
        self.duration = t0 - self._timestamp
        self._timestamp = t0
        self._request.send(TaskStatHelper.connection)
        try:
            reply = GeNlMessage.recv(TaskStatHelper.connection)
        except OSError as e:
            if e.errno == errno.ESRCH:
                # OSError: Netlink error: No such process (3)
                return
            raise
        for attr_type, attr_value in reply.attrs.items():
            #if attr_type == TASKSTATS_TYPE_AGGR_TGID:
            if attr_type == TASKSTATS_TYPE_AGGR_PID:
                reply = attr_value.nested()
                break
        else:
            return
        taskstats_data = reply[TASKSTATS_TYPE_STATS].data
        if len(taskstats_data) < 272:
            # Short reply
            return
        taskstats_version = struct.unpack('H', taskstats_data[:2])[0]
        taskstats_ac_utime = struct.unpack('Q', taskstats_data[152:160])[0]
        taskstats_ac_stime = struct.unpack('Q', taskstats_data[160:168])[0]
        #print 'utime:',taskstats_ac_utime, 'stime:',taskstats_ac_stime
        assert taskstats_version >= 4
        self._update_stats(Stats(taskstats_data))
        return self._stats_delta


class ProcessCounter(object):
    def __init__(self, pid):
        self._pid = pid
        self._update_tids()

    def update_tasks_stats(self):
        tasks_delta = Stats.build_all_zero()
        total_duration = 0
        for task_counter in self._task_counters:
            tasks_delta.accumulate(task_counter.update_task_stats(), tasks_delta)
            total_duration += task_counter.duration
        if not self._task_counters:
            return (None, None)
        return (tasks_delta, int(total_duration/len(self._task_counters)))

    def _update_tids(self):
        tids = self._list_tids()
        self._task_counters = [TaskCounter(tid) for tid in tids]

    def _list_tids(self):
        try:
            tids = list(map(int, os.listdir('/proc/%d/task' % self._pid)))
        except OSError:
            return []
        return tids
