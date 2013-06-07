import time
from threading import Thread, Lock
from Queue import Queue
from taskstats import ProcessCounter, Stats
import subprocess


class ProcessMonitor(object):
    def __init__(self, process_names):
        self._process_names = process_names
        self._process_ids_counter_m = {}
        self._process_id_name_m = {}
        self._process_name_ids_m = {}
        self._update_lock = Lock()
        self._refresh_process_names()
        self._q = Queue(maxsize=1000)
        self._reporter = Thread(target=self._report_worker)
        self._process_name_refresher = Thread(target=self._refresh_process_names_worker)

    def _get_process_ids_by_names(self):
        self._process_id_name_m = {}
        self._process_name_ids_m = {}
        p = subprocess.Popen(['ps', '-ef'], stdout=subprocess.PIPE)
        out, err = p.communicate()
        for line in out.splitlines():
            items = line.split()
            pid = items[1]
            for name in self._process_names:
                if line.find(name) != -1:
                    self._process_id_name_m[pid] = name
                    if name not in self._process_name_ids_m:
                        self._process_name_ids_m[name] = []
                    self._process_name_ids_m[name].append(pid)
                    continue

    def _compute_diff_pid_counter(self):
        counter_pids = set(self._process_ids_counter_m.keys())
        for pid in self._process_id_name_m.keys():
            if pid not in counter_pids:
                self._process_ids_counter_m[pid] = ProcessCounter(int(pid))

        name_ids = set(self._process_id_name_m.keys())
        for pid in counter_pids:
            if pid not in name_ids:
                del self._process_ids_counter_m[pid]

    def _refresh_process_names_worker(self):
        while True:
            self._refresh_process_names()
            time.sleep(60*10)

    def _refresh_process_names(self):
        with self._update_lock:
            self._get_process_ids_by_names()
            self._compute_diff_pid_counter()

    def _update_processes(self):
        m = {}
        for (pid, pcounter) in self._process_ids_counter_m.iteritems():
            (delta, duration) = pcounter.update_tasks_stats()
            if delta:
                m[pid] = {'delta': delta, 'duration':duration}
        return m

    def _trans_id_to_name(self, id_m):
        name_m = {} 
        for (pid, v) in id_m.iteritems():
            name = self._process_id_name_m.get(pid, None)
            if name:
                v0 = name_m.get(name, None)
                if v0:
                    acc_stats = Stats.build_all_zero()
                    v['delta'].accumulate(v0['delta'], acc_stats)
                    name_m[name] = {'delta': acc_stats, 'duration':(int(v0['duration'])+int(v['duration']))/2.0}
                else:
                    name_m[name] = {'delta':v['delta'], 'duration':v['duration']}
        return name_m

    def _refresh_processes(self):
        with self._update_lock:
            id_m = self._update_processes()
            name_m = self._trans_id_to_name(id_m)
            return name_m

    def _report_data(self, data):
        print data

    def _report_worker(self):
        while True:
            item = self._q.get(block=True)
            self._report_data(item)

    def run(self):
        #start reporter first
        self._reporter.setDaemon(True)
        self._reporter.start()

        self._process_name_refresher.setDaemon(True)
        self._process_name_refresher.start()

        while True:
            name_resources_delta = self._refresh_processes()
            try:
                self._q.put_nowait(name_resources_delta)
            except Full,e:
                print e
            time.sleep(10)


if __name__ == '__main__':
    ProcessMonitor(['carbon-cache.py']).run()
