cmake_minimum_required(VERSION 3.15)
project(add C)

find_package(Python3 COMPONENTS Development.Module REQUIRED)
Python3_add_library(add MODULE src/add.c)
set_target_properties(add PROPERTIES
    OUTPUT_NAME "$ENV{JUST_BUILDIT_NAME}"
    SUFFIX      "$ENV{JUST_BUILDIT_EXT_SUFFIX}"
    PREFIX      "")
