pyext:
	meson setup _build --reconfigure -Dbuildtype=release
	meson compile -C _build
	find _build -name "*$(JUST_BUILDIT_EXT_SUFFIX)" \
		-exec cp {} $(JUST_BUILDIT_OUTPUT_DIR)/ \;

clean:
	rm -rf _build
