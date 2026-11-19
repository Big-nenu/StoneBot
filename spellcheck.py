"""Ortografía y sugerencias con el corrector local de Windows."""
import ctypes
import sys
from uuid import UUID


class WindowsSpellChecker:
    def __init__(self):
        self.checker = ctypes.c_void_p()
        self.initialized = False
        if sys.platform != "win32":
            return

        pointer = ctypes.POINTER(ctypes.c_void_p)
        number = ctypes.POINTER(ctypes.c_ulong)
        # Las posiciones son las de las interfaces IUnknown y spellcheck.h del SDK de Windows.
        self.release = ctypes.WINFUNCTYPE(ctypes.c_ulong)(2, "Release")
        create = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_wchar_p, pointer)(5, "CreateSpellChecker")
        self.check = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_wchar_p, pointer)(4, "Check")
        self.suggest = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_wchar_p, pointer)(5, "Suggest")
        self.next_error = ctypes.WINFUNCTYPE(ctypes.c_long, pointer)(3, "Next")
        self.next_string = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_ulong, pointer, number)(3, "Next")
        self.free_string = ctypes.windll.ole32.CoTaskMemFree
        self.free_string.argtypes = [ctypes.c_void_p]
        self.free_string.restype = None
        self.start_index = ctypes.WINFUNCTYPE(ctypes.c_long, number)(3, "get_StartIndex")
        self.error_length = ctypes.WINFUNCTYPE(ctypes.c_long, number)(4, "get_Length")

        factory = ctypes.c_void_p()
        try:
            ctypes.oledll.ole32.CoInitializeEx(None, 2)
            self.initialized = True
            clsid = UUID("7AB36653-1796-484B-BDFA-E74F1DB7C1DC").bytes_le
            iid = UUID("8E018A9D-2415-4677-BF08-794EA61F94BB").bytes_le
            ctypes.oledll.ole32.CoCreateInstance(clsid, None, 1, iid, ctypes.byref(factory))
            for language in ("es-MX", "es-ES", "es-US"):
                try:
                    create(factory, language, ctypes.byref(self.checker))
                except OSError:
                    continue
                self.language = language
                break
        except OSError:
            pass
        finally:
            if factory:
                self.release(factory)
            if not self.checker:
                self.close()

    def close(self):
        if self.checker:
            self.release(self.checker)
            self.checker = ctypes.c_void_p()
        if self.initialized:
            uninitialize = ctypes.windll.ole32.CoUninitialize
            uninitialize.restype = None
            uninitialize()
            self.initialized = False

    def errors(self, text):
        if not self.checker or not text.strip():
            return []
        errors = ctypes.c_void_p()
        spans = []
        try:
            self.check(self.checker, text, ctypes.byref(errors))
            if not errors:
                return spans
            error = ctypes.c_void_p()
            while self.next_error(errors, ctypes.byref(error)) == 0 and error:
                start, length = ctypes.c_ulong(), ctypes.c_ulong()
                try:
                    self.start_index(error, ctypes.byref(start))
                    self.error_length(error, ctypes.byref(length))
                    spans.append((start.value, length.value))
                finally:
                    self.release(error)
                    error = ctypes.c_void_p()
        except OSError:
            return []
        finally:
            if errors:
                self.release(errors)
        return spans


    def suggestions(self, word):
        if not self.checker:
            return []
        results, string, fetched = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_ulong()
        choices = []
        try:
            self.suggest(self.checker, word, ctypes.byref(results))
            while results and len(choices) < 5 and self.next_string(results, 1, ctypes.byref(string),
                                                                    ctypes.byref(fetched)) == 0 and string:
                try:
                    choice = ctypes.wstring_at(string)
                    if choice != word and choice not in choices:
                        choices.append(choice)
                finally:
                    self.free_string(string)
                    string = ctypes.c_void_p()
        except OSError:
            pass
        finally:
            if string:
                self.free_string(string)
            if results:
                self.release(results)
        return choices
