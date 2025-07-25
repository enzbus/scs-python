from glob import glob

from platform import system
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
import argparse
import os
import sys

SCS_ARG_MARK = "--scs"  # used to pass custom arguments to setup

parser = argparse.ArgumentParser(description="Compilation args for SCS.")
parser.add_argument(
    SCS_ARG_MARK,
    dest="scs",
    action="store_true",
    default=False,
    help="Put this first to ensure following arguments are parsed correctly",
)
parser.add_argument(
    "--gpu",
    dest="gpu",
    action="store_true",
    default=False,
    help="Also compile the GPU CUDA version of SCS",
)
parser.add_argument(
    "--mkl",
    dest="mkl",
    action="store_true",
    default=False,
    help="Also compile the MKL version of SCS. MKL must be installed for this "
    "to succeed. This option will be removed soon after which we shall "
    "install the MKL version by default if MKL is available.",
)
parser.add_argument(
    "--cudss",
    dest="cudss",
    action="store_true",
    default=False,
    help="Also compile the cuDSS version of SCS",
)
parser.add_argument(
    "--openmp",
    dest="openmp",
    action="store_true",
    default=False,
    help="Compile with OpenMP parallelization enabled. This can make SCS"
    "faster, but requires a compiler with openMP support, the user "
    "must control how many threads OpenMP uses.",
)
parser.add_argument(
    "--float",
    dest="float32",
    action="store_true",
    default=False,
    help="Use 32 bit (single precision) floats, default is 64 bit",
)
parser.add_argument(
    "--extraverbose",
    dest="extraverbose",
    action="store_true",
    default=False,
    help="Extra verbose SCS (for debugging)",
)
parser.add_argument(
    "--no-gpu-atrans",
    dest="gpu_atrans",
    action="store_false",
    default=True,
    help="use original (non-transposed) A matrix in gpu indirect method",
)
parser.add_argument(
    "--int",
    dest="int32",
    action="store_true",
    default=False,
    help=(
        "Use 32 bit ints, default is 64 bit (GPU code must always use 32 bit "
        "ints, since CUSPARSE only supports 32 bits.)"
    ),
)
parser.add_argument(
    "--blas64",
    dest="blas64",
    action="store_true",
    default=False,
    help="Use 64 bit ints for the blas/lapack libs",
)
args, unknown = parser.parse_known_args()

env_lib_dirs = os.environ.get("BLAS_LAPACK_LIB_PATHS", [])
env_libs = os.environ.get("BLAS_LAPACK_LIBS", [])

print(args)

# necessary to remove SCS args before passing to setup:
if SCS_ARG_MARK in sys.argv:
    sys.argv = sys.argv[0 : sys.argv.index(SCS_ARG_MARK)]

import subprocess

# From: https://stackoverflow.com/questions/60174152/how-do-i-add-pkg-config-the-setup-py-of-a-cython-wrapper
def pkgconfig(package, kw):
    flag_map = {'-I': 'include_dirs', '-L': 'library_dirs', '-l': 'libraries'}
    retcode, output = subprocess.getstatusoutput(
        'pkg-config --cflags --libs {}'.format(package))
    if retcode != 0:
        raise Exception(
            f'Invocation of pkg-config for package {package} failed!', output)
    for token in output.strip().split():
        kw.setdefault(flag_map.get(token[:2]), []).append(token[2:])
    return kw

def get_infos():

    if env_lib_dirs or env_libs:
        print("using environment variables for blas/lapack libraries")
        env_vars = {}
        if env_lib_dirs:
            env_vars["library_dirs"] = [env_lib_dirs]
        if env_libs:
            env_vars["libraries"] = env_libs.split(":")
        return env_vars, {}

    try:
        import numpy
        from numpy.distutils.system_info import get_info

    except ImportError: # Py >= 3.12
        blas_info = pkgconfig('blas', {})
        lapack_info = pkgconfig('lapack', {})
        return blas_info, lapack_info

    # Print out full BLAS / LAPACK info
    numpy.show_config()

    # environment variables not set, using defaults instead
    blas_info = get_info("blas_opt")
    if not blas_info:
        blas_info = get_info("blas")
    print("Blas info:")
    print(blas_info)

    lapack_info = get_info("lapack_opt")
    if not lapack_info:
        lapack_info = get_info("lapack")
    print("Lapack info:")
    print(lapack_info)

    return blas_info, lapack_info


def set_builtin(name, value):
    if isinstance(__builtins__, dict):
        __builtins__[name] = value
    else:
        setattr(__builtins__, name, value)


class build_ext_scs(build_ext):
    def finalize_options(self):
        build_ext.finalize_options(self)
        # Prevent numpy from thinking it is still in its setup process:
        set_builtin("__NUMPY_SETUP__", False)
        import numpy

        self.copy = {"include_dirs": [numpy.get_include()]}

        blas_info, lapack_info = get_infos()

        if blas_info or lapack_info:
            self.copy["define_macros"] = (
                [("USE_LAPACK", None)]
                + blas_info.pop("define_macros", [])
                + lapack_info.pop("define_macros", [])
            )
            self.copy["include_dirs"] += blas_info.pop(
                "include_dirs", []
            ) + lapack_info.pop("include_dirs", [])
            self.copy["library_dirs"] = blas_info.pop(
                "library_dirs", []
            ) + lapack_info.pop("library_dirs", [])
            self.copy["libraries"] = blas_info.pop(
                "libraries", []
            ) + lapack_info.pop("libraries", [])
            self.copy["extra_link_args"] = blas_info.pop(
                "extra_link_args", []
            ) + lapack_info.pop("extra_link_args", [])
            self.copy["extra_compile_args"] = blas_info.pop(
                "extra_compile_args", []
            ) + lapack_info.pop("extra_compile_args", [])

    def build_extension(self, ext):
        for k, v in self.copy.items():
            if not getattr(ext, k, None):
                setattr(ext, k, [])
            getattr(ext, k).extend(v)

        return build_ext.build_extension(self, ext)


def install_scs(**kwargs):
    extra_compile_args = ["-O3"]
    extra_link_args = []
    libraries = []
    sources = (
        ["scs/scspy.c"]
        + glob("scs_source/src/*.c")
        + glob("scs_source/linsys/*.c")
    )
    include_dirs = ["scs_source/include", "scs_source/linsys"]
    define_macros = [("PYTHON", None), ("CTRLC", 1)]
    if args.openmp:
        extra_compile_args += ["-fopenmp"]
        extra_link_args += ["-fopenmp"]
        # define_macros += [("_OPENMP", None)]  # TODO: do we need this?

    if system() == "Linux":
        libraries += ["rt"]
    if args.float32:
        define_macros += [("SFLOAT", 1)]  # single precision floating point
    if args.extraverbose:
        define_macros += [("VERBOSITY", 999)]  # for debugging
    if args.blas64:
        define_macros += [("BLAS64", 1)]  # 64 bit blas
    if not args.int32 and not args.gpu:
        define_macros += [("DLONG", 1)]  # longs for integer type

    _scs_direct = Extension(
        name="_scs_direct",
        sources=sources
        + glob("scs_source/linsys/cpu/direct/*.c")
        + glob("scs_source/linsys/external/amd/*.c")
        + glob("scs_source/linsys/external/qdldl/*.c"),
        depends=glob("scs/*.h"),
        define_macros=list(define_macros),
        include_dirs=include_dirs
        + [
            "scs_source/linsys/cpu/direct/",
            "scs_source/linsys/external/amd",
            "scs_source/linsys/external/dqlql",
        ],
        libraries=list(libraries),
        extra_compile_args=list(extra_compile_args),
        extra_link_args=list(extra_link_args),
    )

    _scs_indirect = Extension(
        name="_scs_indirect",
        sources=sources + glob("scs_source/linsys/cpu/indirect/*.c"),
        depends=glob("scs/*.h"),
        define_macros=list(define_macros)
        + [("PY_INDIRECT", None), ("INDIRECT", 1)],
        include_dirs=include_dirs + ["scs_source/linsys/cpu/indirect/"],
        libraries=list(libraries),
        extra_compile_args=list(extra_compile_args),
        extra_link_args=list(extra_link_args),
    )

    ext_modules = [_scs_direct, _scs_indirect]

    if args.gpu:
        library_dirs = []
        if system() == "Windows":
            include_dirs += [os.environ["CUDA_PATH"] + "/include"]
            library_dirs = [os.environ["CUDA_PATH"] + "/lib/x64"]
        else:
            include_dirs += ["/usr/local/cuda/include"]
            library_dirs = ["/usr/local/cuda/lib", "/usr/local/cuda/lib64"]
        if args.gpu_atrans:  # Should be True by default
            define_macros += [("GPU_TRANSPOSE_MAT", 1)]
        _scs_gpu = Extension(
            name="_scs_gpu",
            sources=sources
            + glob("scs_source/linsys/gpu/*.c")
            + glob("scs_source/linsys/gpu/indirect/*.c"),
            depends=glob("scs/*.h"),
            define_macros=list(define_macros)
            + [("PY_GPU", None), ("INDIRECT", 1)],
            include_dirs=include_dirs
            + ["scs_source/linsys/gpu/", "scs_source/linsys/gpu/indirect"],
            library_dirs=library_dirs,
            libraries=libraries + ["cudart", "cublas", "cusparse"],
            extra_compile_args=list(extra_compile_args),
            extra_link_args=list(extra_link_args),
        )
        ext_modules += [_scs_gpu]

    if args.mkl:
        # TODO: This heuristic attempts to determine if MKL is installed.
        # Replace with something better.
        blibs = None
        blas_info, lapack_info = get_infos()
        if "libraries" in blas_info and "libraries" in lapack_info:
            blibs = blas_info["libraries"] + lapack_info["libraries"]
        if not any("mkl" in s for s in (blibs or [])):
            raise ValueError(
                "MKL not found in blas / lapack info dicts so cannot install "
                "MKL-linked version of SCS. Please install MKL and retry. "
                "If you think this is an error please let us know by opening "
                "a GitHub issue."
            )
        # MKL should be included in the libraries already:
        _scs_mkl = Extension(
            name="_scs_mkl",
            sources=sources + glob("scs_source/linsys/mkl/direct/*.c"),
            depends=glob("scs/*.h"),
            define_macros=list(define_macros) + [("PY_MKL", None)],
            include_dirs=include_dirs + ["scs_source/linsys/mkl/direct/"],
            libraries=list(libraries),
            extra_compile_args=list(extra_compile_args),
            extra_link_args=list(extra_link_args),
        )
        ext_modules += [_scs_mkl]

    if args.cudss:
        # MKL should be included in the libraries already:
        _scs_cudss = Extension(
            name="_scs_cudss",
            sources=sources + glob("scs_source/linsys/cudss/direct/*.c"),
            depends=glob("scs/*.h"),
            define_macros=list(define_macros) + [("PY_CUDSS", None)],
            include_dirs=include_dirs + ["scs_source/linsys/cudss/direct/"],
            libraries=list(libraries),
            extra_compile_args=list(extra_compile_args),
            extra_link_args=list(extra_link_args),
        )
        ext_modules += [_scs_cudss]


    setup(
        name="scs",
        version="3.2.7",
        author="Brendan O'Donoghue",
        author_email="bodonoghue85@gmail.com",
        url="http://github.com/cvxgrp/scs",
        description="scs: splitting conic solver",
        package_dir={"scs": "scs"},
        packages=["scs"],
        ext_modules=ext_modules,
        cmdclass={"build_ext": build_ext_scs},
        setup_requires=["numpy >= 1.7"],
        install_requires=["numpy >= 1.7", "scipy >= 0.13.2"],
        license="MIT",
        zip_safe=False,
        # TODO: update this:
        long_description=(
            "Solves convex quadratic cone programs via operator splitting. "
            "Can solve: linear programs (LPs), second-order cone "
            "programs (SOCPs), semidefinite programs (SDPs), "
            "exponential cone programs (ECPs), and power cone "
            "programs (PCPs), or problems with any combination of "
            "those cones. See https://www.cvxgrp.org/scs/ for "
            "more details."
        ),
    )


install_scs()
