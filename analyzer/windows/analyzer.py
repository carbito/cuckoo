import sys
from ctypes import *
from threading import Lock, Thread, Timer

from lib.core.defines import *
from lib.core.startup import create_folders
from lib.core.privileges import grant_debug_privilege
from lib.api.process import Process

BUFSIZE      = 512
PROCESS_LIST = []
PROCESS_LOCK = Lock()

def add_pid(pid):
    PROCESS_LOCK.acquire()

    if type(pid) == long or type(pid) == int or type(pid) == str:
        PROCESS_LIST.append(pid)

    PROCESS_LOCK.release()

def add_pids(pids):
    if type(pids) == list:
        for pid in pids:
            add_pid(pid)
    else:
        add_pid(pids)

class PipeHandler(Thread):
    def __init__(self, h_pipe):
        Thread.__init__(self)
        self.h_pipe = h_pipe

    def run(self):
        data = create_string_buffer(BUFSIZE)

        while True:
            bytes_read = c_int(0)

            success = KERNEL32.ReadFile(self.h_pipe,
                                        data,
                                        sizeof(data),
                                        byref(bytes_read),
                                        None)

            if not success or bytes_read.value == 0:
                if KERNEL32.GetLastError() == ERROR_BROKEN_PIPE:
                    pass
                break

        if data:
            command = data.value.strip()
                
            if command.startswith("PID:"):
                pid = command[4:]
                if pid.isdigit():
                    pid = int(pid)
                    if pid not in PROCESS_LIST:
                        proc = Process(pid=pid)
                        proc.inject()
                        add_pids(proc.pid)
            elif command.startswith("FILE:"):
                file_path = command[5:]

        return True

class PipeServer(Thread):
    def __init__(self, pipe_name = "\\\\.\\pipe\\cuckoo"):
        Thread.__init__(self)
        self.pipe_name = pipe_name
        self.do_run = True

    def stop(self):
        self.do_run = False

    def run(self):
        while self.do_run:
            h_pipe = KERNEL32.CreateNamedPipeA(self.pipe_name,
                                               PIPE_ACCESS_DUPLEX,
                                               PIPE_TYPE_MESSAGE | \
                                               PIPE_READMODE_MESSAGE | \
                                               PIPE_WAIT,
                                               PIPE_UNLIMITED_INSTANCES,
                                               BUFSIZE,
                                               BUFSIZE,
                                               0,
                                               None)

            if h_pipe == INVALID_HANDLE_VALUE:
                return False

            if KERNEL32.ConnectNamedPipe(h_pipe, None):
                handler = PipeHandler(h_pipe)
                handler.daemon = True
                handler.start()
            else:
                KERNEL32.CloseHandle(h_pipe)

        return True

class Analyzer:
    def __init__(self):
        self.do_run = True
        self.pipe   = None

    def prepare(self):
        grant_debug_privilege()
        create_folders()
        self.pipe = PipeServer()
        self.pipe.daemon = True
        self.pipe.start()

    def complete(self):
        self.pipe.stop()

    def stop(self):
        self.do_run = False

    def run(self):
        self.prepare()

        try:
            package_name = "packages.exe"
            package = __import__(package_name,
                                 globals(),
                                 locals(),
                                 ["Package"],
                                 -1)
        except ImportError:
            sys.exit("Unable to import package \"%s\", does not exist."
                     % package_name)

        pack = package.Package()

        timer = Timer(120.0, self.stop)
        timer.start()

        try:
            pids = pack.run()
        except AttributeError:
            sys.exit("The package \"%s\" doesn't contain a run function."
                     % package_name)

        add_pids(pids)

        while self.do_run:
            PROCESS_LOCK.acquire()

            try:
                for pid in PROCESS_LIST:
                    if not Process(pid=pid).is_alive():
                        PROCESS_LIST.remove(pid)

                if len(PROCESS_LIST) == 0:
                    timer.cancel()
                    break

                try:
                    if not pack.check():
                        timer.cancel()
                        break
                except AttributeError:
                    pass
            finally:
                PROCESS_LOCK.release()
                KERNEL32.Sleep(1000)

        try:
            pack.finish()
        except AttributeError:
            pass

        self.complete()

        return True

if __name__ == "__main__":
    status = False
    error  = None

    try:
        analyzer = Analyzer()
        status = analyzer.run()
    except KeyboardInterrupt:
        error = "Keyboard Interrupt"
    except SystemExit as e:
        error = e
    finally:
        print "STATUS", status
        print "ERROR", error