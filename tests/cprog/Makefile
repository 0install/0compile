PC_DIR=${DISTDIR}/pkgconfig

all: main
	./main
	[ -d "${PC_DIR}" ] || mkdir "${PC_DIR}"
	echo "prefix=${DISTDIR}" > "${PC_DIR}/cprog.pc"
