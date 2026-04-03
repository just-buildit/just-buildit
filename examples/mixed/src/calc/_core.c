/*
 * _core.c — just-build mixed pure/platform example.
 *
 * Exports: calc._core.add(a, b) -> int
 *          calc._core.multiply(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
core_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyObject *
core_multiply(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a * b);
}

static PyMethodDef CoreMethods[] = {
    {"add",      core_add,      METH_VARARGS, "Add two integers."},
    {"multiply", core_multiply, METH_VARARGS, "Multiply two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef coremodule = {
    PyModuleDef_HEAD_INIT, "_core", NULL, -1, CoreMethods
};

PyMODINIT_FUNC
PyInit__core(void) { return PyModule_Create(&coremodule); }
