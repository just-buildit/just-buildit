/*
 * greeter.c — just-buildit Bazel example.
 *
 * Exports: greeter.greet(name) -> str
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdio.h>

static PyObject *
greeter_greet(PyObject *self, PyObject *args)
{
    const char *name;
    if (!PyArg_ParseTuple(args, "s", &name))
        return NULL;
    char buf[256];
    snprintf(buf, sizeof(buf), "Hello, %s!", name);
    return PyUnicode_FromString(buf);
}

static PyMethodDef GreeterMethods[] = {
    {"greet", greeter_greet, METH_VARARGS, "Greet by name."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef greetermodule = {
    PyModuleDef_HEAD_INIT, "greeter", NULL, -1, GreeterMethods
};

PyMODINIT_FUNC
PyInit_greeter(void) { return PyModule_Create(&greetermodule); }
