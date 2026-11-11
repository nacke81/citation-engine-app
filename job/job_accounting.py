"""JOBOBJECT_BASIC_ACCOUNTING_INFORMATION as a real ctypes Structure (t_15f7ec86 round 3).
Pure ctypes, no kernel32, so layout can be tested on any OS. ActiveProcesses is at offset 40 (TotalProcesses is 36); sizeof is 48."""
import ctypes


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", ctypes.c_uint32), ("TotalProcesses", ctypes.c_uint32),
                ("ActiveProcesses", ctypes.c_uint32), ("TotalTerminatedProcesses", ctypes.c_uint32)]


JobObjectBasicAccountingInformation = 1
