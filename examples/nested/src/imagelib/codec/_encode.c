/*
 * _encode.c — just-buildit nested example: imagelib.codec._encode
 *
 * Exports: encode(value) -> int   (returns value * 3)
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
codec_encode(PyObject *self, PyObject *args)
{
    long value;
    if (!PyArg_ParseTuple(args, "l", &value))
        return NULL;
    return PyLong_FromLong(value * 3);
}

static PyMethodDef EncodeMethods[] = {
    {"encode", codec_encode, METH_VARARGS, "Triple a value."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef encodemodule = {
    PyModuleDef_HEAD_INIT, "_encode", NULL, -1, EncodeMethods
};

PyMODINIT_FUNC
PyInit__encode(void) { return PyModule_Create(&encodemodule); }
