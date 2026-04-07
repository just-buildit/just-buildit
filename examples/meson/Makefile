pyext:
	meson setup _build --reconfigure -Dbuildtype=release
	meson compile -C _build
	find _build -name "*$(JUST_BUILD_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILD_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
