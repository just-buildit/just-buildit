/*
 * hello.c — minimal CPython extension for just-buildit integration tests.
 *
 * Exports one function: hello.add(a, b) -> int
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
hello_add(PyObject *self, PyObject *args)
{
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b))
        return NULL;
    return PyLong_FromLong(a + b);
}

static PyMethodDef HelloMethods[] = {
    {"add", hello_add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef hellomodule = {
    PyModuleDef_HEAD_INIT,
    "hello",
    NULL,
    -1,
    HelloMethods
};

PyMODINIT_FUNC
PyInit_hello(void)
{
    return PyModule_Create(&hellomodule);
}
