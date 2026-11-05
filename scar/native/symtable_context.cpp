// CPython 3.14.7 only: official symtable entry, with explicit compiler flags.
#define PY_SSIZE_T_CLEAN
#define Py_BUILD_CORE
#include <Python.h>
#include "internal/pycore_symtable.h"
#include <cstring>
#ifndef SCAR_SYMTABLE_DIRECT
#include <dlfcn.h>
#endif

#if PY_VERSION_HEX != 0x030e07f0 || defined(Py_GIL_DISABLED)
#error "SCAR symtable adapter requires GIL-enabled CPython 3.14.7 final"
#endif

using Build = symtable *(*)(const char *, PyObject *, int, PyCompilerFlags *);
using Free = void (*)(symtable *);

static Build builder() {
#ifdef SCAR_SYMTABLE_DIRECT
    return &_Py_SymtableStringObjectFlags;
#else
    return reinterpret_cast<Build>(dlsym(RTLD_DEFAULT, "_Py_SymtableStringObjectFlags"));
#endif
}

static Free release_table() {
#ifdef SCAR_SYMTABLE_DIRECT
    return &_PySymtable_Free;
#else
    return reinterpret_cast<Free>(dlsym(RTLD_DEFAULT, "_PySymtable_Free"));
#endif
}

static PyObject *probe(PyObject *, PyObject *) {
    return Py_BuildValue("{s:O,s:O,s:i,s:i,s:s}",
        "builder", builder() ? Py_True : Py_False,
        "free", release_table() ? Py_True : Py_False,
        "unicode_transport_flags", PyCF_SOURCE_IS_UTF8 | PyCF_IGNORE_COOKIE,
        "compiler_flag_mask", PyCF_MASK | PyCF_MASK_OBSOLETE | PyCF_COMPILE_MASK,
#ifdef SCAR_SYMTABLE_DIRECT
        "binding", "DIRECT_LINK_TO_SAME_HELPER_RUNTIME");
#else
        "binding", "CURRENT_PROCESS_EXPORTED_SYMBOLS_ONLY");
#endif
}

static PyObject *raw_symtable(PyObject *, PyObject *args) {
    PyObject *source, *filename;
    const char *mode;
    int flags;
    if (!PyArg_ParseTuple(args, "UUsi:symtable_flags", &source, &filename, &mode, &flags))
        return nullptr;
    if (flags < 0 || (flags & ~(PyCF_MASK | PyCF_MASK_OBSOLETE | PyCF_COMPILE_MASK))) {
        PyErr_SetString(PyExc_ValueError, "unsupported explicit compiler flags");
        return nullptr;
    }
    Build build = builder();
    Free free_table = release_table();
    if (!build || !free_table) {
        PyErr_SetString(PyExc_NotImplementedError, "official symtable flags entry is not exported by this runtime");
        return nullptr;
    }
    int start;
    if (!std::strcmp(mode, "exec")) start = Py_file_input;
    else if (!std::strcmp(mode, "eval")) start = Py_eval_input;
    else if (!std::strcmp(mode, "single")) start = Py_single_input;
    else {
        PyErr_SetString(PyExc_ValueError, "mode must be exec, eval or single");
        return nullptr;
    }
    Py_ssize_t size;
    const char *text = PyUnicode_AsUTF8AndSize(source, &size);
    if (!text) return nullptr;
    if (static_cast<Py_ssize_t>(std::strlen(text)) != size) {
        PyErr_SetString(PyExc_SyntaxError, "source code string cannot contain null bytes");
        return nullptr;
    }
    // Matches the official Unicode _Py_SourceAsString path. There is no
    // PyEval_MergeCompilerFlags call and no inspection of a Python caller.
    PyCompilerFlags context = {flags | PyCF_SOURCE_IS_UTF8 | PyCF_IGNORE_COOKIE, PY_MINOR_VERSION};
    symtable *table = build(text, filename, start, &context);
    if (!table) return nullptr;
    PyObject *result = Py_NewRef(reinterpret_cast<PyObject *>(table->st_top));
    free_table(table);
    return result;
}

static PyMethodDef methods[] = {
    {"probe", probe, METH_NOARGS, "Describe the version-limited native entry."},
    {"symtable_flags", raw_symtable, METH_VARARGS, "Official raw symtable with explicit flags; no caller inheritance."},
    {nullptr, nullptr, 0, nullptr}
};
static PyModuleDef module = {PyModuleDef_HEAD_INIT, "_scar_symtable_context", nullptr, -1, methods};

PyMODINIT_FUNC PyInit__scar_symtable_context() {
    if (std::strncmp(Py_GetVersion(), "3.14.7 ", 7)) {
        PyErr_SetString(PyExc_ImportError, "adapter runtime is not CPython 3.14.7");
        return nullptr;
    }
    return PyModule_Create(&module);
}
