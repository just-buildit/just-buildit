pyext:
	cmake -B _build -DPython3_EXECUTABLE=$(JUST_BUILD_PYTHON)
	cmake --build _build --target add
	find _build -maxdepth 3 -name "$(JUST_BUILD_NAME)$(JUST_BUILD_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILD_OUTPUT_DIR)/ \;

.PHONY: pyext
