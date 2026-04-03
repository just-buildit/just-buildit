/*
 * add.c — just-build Meson example.
 *
 * Exports: add.add(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
add_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyMethodDef AddMethods[] = {
    {"add", add_add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef addmodule = {
    PyModuleDef_HEAD_INIT, "add", NULL, -1, AddMethods
};

PyMODINIT_FUNC
PyInit_add(void) { return PyModule_Create(&addmodule); }
