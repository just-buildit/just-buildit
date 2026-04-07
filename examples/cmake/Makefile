pyext:
	cmake -S . -B _build -DCMAKE_BUILD_TYPE=Release
	cmake --build _build
	find _build -name "*$(JUST_BUILD_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILD_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
