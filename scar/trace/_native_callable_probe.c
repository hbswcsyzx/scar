/* Read only public, full-ABI CPython callable records. No Python lookup/call. */
#ifdef Py_LIMITED_API
#error "SCAR native callable probe requires the CPython full ABI"
#endif
#include <Python.h>
#include <stdint.h>
#include <string.h>

#if PY_VERSION_HEX != 0x030e07f0
#error "SCAR native callable probe supports CPython 3.14.7 only"
#endif
#ifdef Py_GIL_DISABLED
#error "SCAR native callable probe does not support free-threaded builds"
#endif
#if !defined(__linux__) || !defined(__x86_64__)
#error "SCAR native callable probe supports Linux x86-64 only"
#endif

_Static_assert(sizeof(uintptr_t) == 8, "64-bit addresses required");
_Static_assert(sizeof(PyCFunction) == sizeof(uintptr_t), "function pointer ABI");
_Static_assert(sizeof(vectorcallfunc) == sizeof(uintptr_t), "vectorcall ABI");
_Static_assert(sizeof(ternaryfunc) == sizeof(uintptr_t), "tp_call ABI");
_Static_assert(sizeof(wrapperfunc) == sizeof(uintptr_t), "wrapper ABI");

static int
put(PyObject *result, const char *key, PyObject *owned)
{
    if (owned == NULL) {
        return -1;
    }
    int status = PyDict_SetItemString(result, key, owned);
    Py_DECREF(owned);
    return status;
}

static PyObject *
function_address(const void *field, size_t size)
{
    uintptr_t bits = 0;
    if (size != sizeof(bits)) {
        PyErr_SetString(PyExc_RuntimeError, "unsupported function pointer ABI");
        return NULL;
    }
    /* Linux x86-64 representation only. Never dereference the code address. */
    memcpy(&bits, field, size);
    return bits == 0 ? Py_NewRef(Py_None) : PyLong_FromUnsignedLongLong(bits);
}

static PyObject *
object_address(const void *pointer)
{
    return pointer == NULL ? Py_NewRef(Py_None) : PyLong_FromVoidPtr((void *)pointer);
}

static int
method_fields(PyObject *result, PyMethodDef *method)
{
    if (method == NULL) {
        return 0;
    }
    if (put(result, "kind", PyUnicode_FromString("METHOD_DEF")) < 0
            || put(result, "methoddef_address", object_address(method)) < 0
            || put(result, "method_flags", PyLong_FromLong(method->ml_flags)) < 0
            || (method->ml_meth != NULL && put(result, "entrypoint_address", function_address(
                &method->ml_meth, sizeof(method->ml_meth))) < 0)) {
        return -1;
    }
    return method->ml_name == NULL ? 0 : put(result, "method_name", PyUnicode_FromString(method->ml_name));
}

static PyObject *
probe(PyObject *module, PyObject *callable)
{
    (void)module;
    if (!PyGILState_Check()) {
        PyErr_SetString(PyExc_RuntimeError, "native callable probe requires the GIL");
        return NULL;
    }
    PyObject *result = PyDict_New();
    if (result == NULL) {
        return NULL;
    }
    if (put(result, "kind", PyUnicode_FromString("UNKNOWN")) < 0
            || put(result, "exact_type", Py_NewRef((PyObject *)Py_TYPE(callable))) < 0
            || (Py_TYPE(callable)->tp_name != NULL && put(result, "exact_type_name",
                PyUnicode_FromString(Py_TYPE(callable)->tp_name)) < 0)) {
        goto error;
    }

    if (PyCFunction_CheckExact(callable) || PyCMethod_CheckExact(callable)) {
        PyCFunctionObject *function = (PyCFunctionObject *)callable;
        if (method_fields(result, function->m_ml) < 0) {
            goto error;
        }
        if (function->m_ml != NULL) {
            PyObject *self = PyCFunction_GET_SELF(callable);
            if (self != NULL && put(result, "bound_self", Py_NewRef(self)) < 0) {
                goto error;
            }
        }
        if (PyCMethod_CheckExact(callable)) {
            PyTypeObject *owner = ((PyCMethodObject *)callable)->mm_class;
            if (owner != NULL && put(result, "defining_class", Py_NewRef((PyObject *)owner)) < 0) {
                goto error;
            }
        }
    }
    else if (Py_IS_TYPE(callable, &PyMethodDescr_Type)
            || Py_IS_TYPE(callable, &PyClassMethodDescr_Type)) {
        if (method_fields(result, ((PyMethodDescrObject *)callable)->d_method) < 0) {
            goto error;
        }
        PyTypeObject *owner = PyDescr_TYPE(callable);
        if (owner != NULL && (put(result, "descriptor_owner", Py_NewRef((PyObject *)owner)) < 0
                || (owner->tp_name != NULL && put(result, "descriptor_owner_name",
                    PyUnicode_FromString(owner->tp_name)) < 0))) {
            goto error;
        }
    }
    else if (Py_IS_TYPE(callable, &PyWrapperDescr_Type)) {
        PyWrapperDescrObject *descriptor = (PyWrapperDescrObject *)callable;
        struct wrapperbase *base = descriptor->d_base;
        if (put(result, "kind", PyUnicode_FromString("WRAPPER_SLOT")) < 0
                || (descriptor->d_wrapped != NULL && put(result, "wrapped_slot_address",
                    object_address(descriptor->d_wrapped)) < 0)) {
            goto error;
        }
        if (base != NULL && (put(result, "wrapper_flags", PyLong_FromLong(base->flags)) < 0
                || (base->wrapper != NULL && put(result, "wrapper_adapter_address", function_address(
                    &base->wrapper, sizeof(base->wrapper))) < 0)
                || (base->name != NULL && put(result, "wrapper_name", PyUnicode_FromString(base->name)) < 0))) {
            goto error;
        }
        PyTypeObject *owner = PyDescr_TYPE(callable);
        if (owner != NULL && (put(result, "descriptor_owner", Py_NewRef((PyObject *)owner)) < 0
                || (owner->tp_name != NULL && put(result, "descriptor_owner_name",
                    PyUnicode_FromString(owner->tp_name)) < 0))) {
            goto error;
        }
    }
    else {
        /* An unknown object's tp_call is not proof of a native implementation. */
        return result;
    }

    vectorcallfunc vectorcall = PyVectorcall_Function(callable);
    ternaryfunc tp_call = Py_TYPE(callable)->tp_call;
    if ((vectorcall != NULL && put(result, "dispatcher_vectorcall_address",
            function_address(&vectorcall, sizeof(vectorcall))) < 0)
            || (tp_call != NULL && put(result, "dispatcher_tp_call_address",
                function_address(&tp_call, sizeof(tp_call))) < 0)) {
        goto error;
    }
    return result;
error:
    Py_DECREF(result);
    return NULL;
}

static PyMethodDef methods[] = {
    {"probe", probe, METH_O, "Read an exact native callable's records without invoking it."},
    {NULL, NULL, 0, NULL}
};

static int
module_exec(PyObject *module)
{
    if (Py_Version != PY_VERSION_HEX) {
        PyErr_SetString(PyExc_ImportError, "native callable probe runtime/header version mismatch");
        return -1;
    }
    return PyModule_AddStringConstant(module, "ADDRESS_SCOPE", "CURRENT_PROCESS_LOADED_INSTANCE") < 0
        || PyModule_AddStringConstant(module, "CPYTHON_VERSION", PY_VERSION) < 0 ? -1 : 0;
}

static PyModuleDef_Slot slots[] = {
    {Py_mod_exec, module_exec},
    {Py_mod_multiple_interpreters, Py_MOD_MULTIPLE_INTERPRETERS_NOT_SUPPORTED},
    {Py_mod_gil, Py_MOD_GIL_USED},
    {0, NULL}
};

static struct PyModuleDef definition = {
    PyModuleDef_HEAD_INIT,
    .m_name = "_native_callable_probe",
    .m_doc = "CPython 3.14.7 GIL Linux x86-64 process-local callable evidence.",
    .m_size = 0,
    .m_methods = methods,
    .m_slots = slots,
};

PyMODINIT_FUNC
PyInit__native_callable_probe(void)
{
    return PyModuleDef_Init(&definition);
}
