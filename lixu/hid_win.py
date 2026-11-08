"""Acces HID direct pe Windows prin ctypes (hid.dll + setupapi.dll + kernel32.dll).

Replică ce face OemDrv.exe: enumeră toate interfețele HID, citește HIDP_CAPS
și alege colecția după FeatureReportByteLength. Nu are dependențe externe.
"""

from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass
from typing import List, Optional

if sys.platform != "win32":  # pragma: no cover - modulul e folosit doar pe Windows
    raise ImportError("hid_win funcționează doar pe Windows")

from ctypes import wintypes

_hid = ctypes.WinDLL("hid.dll")
_setupapi = ctypes.WinDLL("setupapi.dll", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
HIDP_STATUS_SUCCESS = 0x00110000


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetHidGuid.restype = None
_hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidP_GetCaps.restype = ctypes.c_long
_hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetProductString.restype = wintypes.BOOLEAN
_hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetManufacturerString.restype = wintypes.BOOLEAN
_hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_SetFeature.restype = wintypes.BOOLEAN
_hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
_hid.HidD_GetFeature.restype = wintypes.BOOLEAN

_setupapi.SetupDiGetClassDevsW.argtypes = [
    ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD,
]
_setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
_setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


@dataclass
class HidInterface:
    path: str
    vendor_id: int
    product_id: int
    version: int
    usage_page: int
    usage: int
    input_len: int
    output_len: int
    feature_len: int
    product: str = ""
    manufacturer: str = ""

    @property
    def interface_number(self) -> Optional[int]:
        m = re.search(r"mi_([0-9a-f]{2})", self.path, re.IGNORECASE)
        return int(m.group(1), 16) if m else None


def _open(path: str, access: int) -> Optional[int]:
    handle = _kernel32.CreateFileW(
        path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None
    )
    if handle in (None, 0, INVALID_HANDLE_VALUE):
        return None
    return handle


def _hid_string(func, handle) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if func(handle, buf, ctypes.sizeof(buf)):
        return buf.value.strip()
    return ""


def _device_paths() -> List[str]:
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if info in (None, INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error())
    paths: List[str] = []
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(
                info, None, ctypes.byref(guid), index, ctypes.byref(iface)
            ):
                break
            index += 1
            required = wintypes.DWORD(0)
            _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(iface), None, 0, ctypes.byref(required), None
            )
            if not required.value:
                continue
            buf = ctypes.create_string_buffer(required.value)
            # cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W): 8 pe x64, 6 pe x86.
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if not _setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(iface), buf, required, None, None
            ):
                continue
            paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def enumerate_interfaces(vendor_id: Optional[int] = None, product_id: Optional[int] = None) -> List[HidInterface]:
    result: List[HidInterface] = []
    for path in _device_paths():
        handle = _open(path, 0)  # acces 0 = doar interogare, merge și pentru tastatura de sistem
        if handle is None:
            continue
        try:
            attrs = HIDD_ATTRIBUTES()
            attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
            if not _hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
                continue
            if vendor_id is not None and attrs.VendorID != vendor_id:
                continue
            if product_id is not None and attrs.ProductID != product_id:
                continue
            preparsed = ctypes.c_void_p()
            if not _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                continue
            try:
                caps = HIDP_CAPS()
                if _hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                    continue
            finally:
                _hid.HidD_FreePreparsedData(preparsed)
            result.append(
                HidInterface(
                    path=path,
                    vendor_id=attrs.VendorID,
                    product_id=attrs.ProductID,
                    version=attrs.VersionNumber,
                    usage_page=caps.UsagePage,
                    usage=caps.Usage,
                    input_len=caps.InputReportByteLength,
                    output_len=caps.OutputReportByteLength,
                    feature_len=caps.FeatureReportByteLength,
                    product=_hid_string(_hid.HidD_GetProductString, handle),
                    manufacturer=_hid_string(_hid.HidD_GetManufacturerString, handle),
                )
            )
        finally:
            _kernel32.CloseHandle(handle)
    return result


class HidHandle:
    def __init__(self, interface: HidInterface):
        self.interface = interface
        handle = _open(interface.path, GENERIC_READ | GENERIC_WRITE)
        if handle is None:
            raise OSError(
                f"nu pot deschide {interface.path}: {ctypes.WinError(ctypes.get_last_error())}"
            )
        self._handle = handle

    def set_feature(self, data: bytes) -> None:
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        if not _hid.HidD_SetFeature(self._handle, buf, len(data)):
            raise OSError(f"HidD_SetFeature a eșuat: {ctypes.WinError(ctypes.get_last_error())}")

    def get_feature(self, report_id: int, length: int) -> bytes:
        buf = ctypes.create_string_buffer(length)
        buf[0] = report_id
        if not _hid.HidD_GetFeature(self._handle, buf, length):
            raise OSError(f"HidD_GetFeature a eșuat: {ctypes.WinError(ctypes.get_last_error())}")
        return buf.raw

    def close(self) -> None:
        if self._handle:
            _kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> "HidHandle":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Citire/scriere de rapoarte input/output (folosit de Logitech HID++).
# Fișierul e deschis cu FILE_FLAG_OVERLAPPED, ca citirea să aibă timeout.

FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.WriteFile.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_kernel32.GetOverlappedResult.restype = wintypes.BOOL
_kernel32.CancelIo.argtypes = [wintypes.HANDLE]
_kernel32.CancelIo.restype = wintypes.BOOL


class HidStream:
    """Rapoarte input/output pe o colecție HID (scriere + citire cu timeout)."""

    def __init__(self, interface: HidInterface):
        self.interface = interface
        handle = _kernel32.CreateFileW(
            interface.path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None,
        )
        if handle in (None, 0, INVALID_HANDLE_VALUE):
            raise OSError(f"nu pot deschide {interface.path}: {ctypes.WinError(ctypes.get_last_error())}")
        self._handle = handle
        self._read_event = _kernel32.CreateEventW(None, True, False, None)
        self._write_event = _kernel32.CreateEventW(None, True, False, None)

    def _io(self, func, buf, length: int, event, timeout_ms: int) -> Optional[int]:
        ov = OVERLAPPED()
        ov.hEvent = event
        _kernel32.ResetEvent(event)
        done = wintypes.DWORD(0)
        if not func(self._handle, buf, length, None, ctypes.byref(ov)):
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(f"I/O HID eșuat: {ctypes.WinError(err)}")
            if _kernel32.WaitForSingleObject(event, timeout_ms) == WAIT_TIMEOUT:
                _kernel32.CancelIo(self._handle)
                _kernel32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(done), True)
                return None
        if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(ov), ctypes.byref(done), False):
            raise OSError(f"I/O HID eșuat: {ctypes.WinError(ctypes.get_last_error())}")
        return done.value

    def write(self, data: bytes) -> None:
        length = max(len(data), self.interface.output_len)
        buf = ctypes.create_string_buffer(bytes(data).ljust(length, b"\x00"), length)
        if self._io(_kernel32.WriteFile, buf, length, self._write_event, 1000) is None:
            raise TimeoutError("scriere HID expirată")

    def read(self, timeout: float) -> Optional[bytes]:
        length = max(1, self.interface.input_len)
        buf = ctypes.create_string_buffer(length)
        n = self._io(_kernel32.ReadFile, buf, length, self._read_event, max(0, int(timeout * 1000)))
        return None if n is None else buf.raw[:n]

    def close(self) -> None:
        if self._handle:
            for h in (self._handle, self._read_event, self._write_event):
                _kernel32.CloseHandle(h)
            self._handle = None
