LIB_DIR=${DISTDIR}/lib
PC_DIR=${DISTDIR}/pkgconfig

all: main
	./main
	[ -d "${PC_DIR}" ] || mkdir "${PC_DIR}"
	echo "prefix=${DISTDIR}" > "${PC_DIR}/cprog.pc"
	[ -d "${LIB_DIR}" ] || mkdir "${LIB_DIR}"
	echo "# Please DO NOT delete this file!"  >> "${LIB_DIR}/bad.la"
	echo "# Innocent file"  >> "${LIB_DIR}/good.la"
	echo "# Please DO NOT delete this file!"  >> "${LIB_DIR}/nice.ok"
