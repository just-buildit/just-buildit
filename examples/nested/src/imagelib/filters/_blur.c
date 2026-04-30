/*
 * _blur.c — just-buildit nested example: imagelib.filters._blur
 *
 * Exports: blur(value) -> int   (returns value // 2)
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
filters_blur(PyObject *self, PyObject *args)
{
    long value;
    if (!PyArg_ParseTuple(args, "l", &value))
        return NULL;
    return PyLong_FromLong(value / 2);
}

static PyMethodDef BlurMethods[] = {
    {"blur", filters_blur, METH_VARARGS, "Halve a pixel value."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef blurmodule = {
    PyModuleDef_HEAD_INIT, "_blur", NULL, -1, BlurMethods
};

PyMODINIT_FUNC
PyInit__blur(void) { return PyModule_Create(&blurmodule); }
