pyext:
	cmake -S . -B _build -DCMAKE_BUILD_TYPE=Release
	cmake --build _build
	find _build -name "*$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
