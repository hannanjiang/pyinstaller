#! /usr/bin/env python
#
# Configure PyInstaller for the current Python installation.
#
# Copyright (C) 2005, Giovanni Bajo
# Based on previous work under copyright (c) 2002 McMillan Enterprises, Inc.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA

import os
import sys
import shutil
import re
import time
import inspect

from PyInstaller import HOMEPATH, CONFIGDIR, DEFAULT_CONFIGFILE, PLATFORM
from PyInstaller import is_win, is_unix, is_darwin, is_py24, get_version

import PyInstaller.mf as mf
import PyInstaller.bindepend as bindepend
import PyInstaller.build as build
import PyInstaller.compat as compat

from PyInstaller.depend import dylib

import PyInstaller.log as logging
logger = logging.getLogger('PyInstaller.configure')


def _write_textfile(filename, text):
    """
    Write `text` into file `filename`. If the target directory does
    not exist, create it.
    """
    dirname = os.path.dirname(filename)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    outf = open(filename, 'w')
    outf.write(text)
    outf.close()


def find_EXE_dependencies(config):
    logger.info("Computing EXE_dependencies")
    python = sys.executable
    config['python'] = python
    config['target_platform'] = sys.platform


def test_TCL_TK(config):

    # TCL_root, TK_root and support/useTK.py
    logger.info("Finding TCL/TK...")

    if is_win:
        pattern = r'(?i)tcl(\d\d)\.dll'
    elif is_unix:
        pattern = r'libtcl(\d\.\d)?\.so'
    elif is_darwin:
        pattern = r'_tkinter'
    else:
        # If no pattern is in place for this platform, skip TCL/TK detection.
        logger.info("... skipping TCL/TK detection on this target platform (%s)"
                    % sys.platform)

    if not (is_win):
        save_exclude = dylib.exclude_list
        dylib.exclude_list = None

    a = mf.ImportTracker()
    a.analyze_r('Tkinter')
    binaries = []
    for modnm, mod in a.modules.items():
        if isinstance(mod, mf.ExtensionModule):
            binaries.append((mod.__name__, mod.__file__, 'EXTENSION'))
    # Always add python's dependencies first
    # This ensures that assembly depencies under Windows get pulled in
    # first and we do not need to add assembly DLLs to the exclude list
    # explicitly
    binaries.extend(bindepend.Dependencies([('', sys.executable, '')]))
    binaries.extend(bindepend.Dependencies(binaries))
    for nm, fnm, typ in binaries:
        mo = re.match(pattern, nm)
        if not mo:
            continue
        if not is_darwin:
            ver = mo.group(1)
            tclbindir = os.path.dirname(fnm)
            if is_win:
                ver = ver[0] + '.' + ver[1:]
            elif ver is None:
                # we found "libtcl.so.0" so we need to get the version from the lib directory
                for name in os.listdir(tclbindir):
                    mo = re.match(r'tcl(\d.\d)', name)
                    if mo:
                        ver = mo.group(1)
            logger.info("found TCL/TK version %s", ver)
            tclnm = 'tcl%s' % ver
            tknm = 'tk%s' % ver
            # Linux: /usr/lib with the .tcl files in /usr/lib/tcl8.3 and /usr/lib/tk8.3
            # Windows: Python21/DLLs with the .tcl files in Python21/tcl/tcl8.3 and Python21/tcl/tk8.3
            #      or  D:/Programs/Tcl/bin with the .tcl files in D:/Programs/Tcl/lib/tcl8.0 and D:/Programs/Tcl/lib/tk8.0
            if is_win:
                for attempt in ['../tcl', '../lib']:
                    if os.path.exists(os.path.join(tclbindir, attempt, tclnm)):
                        config['TCL_root'] = os.path.join(tclbindir, attempt, tclnm)
                        config['TK_root'] = os.path.join(tclbindir, attempt, tknm)
                        break  # for attempt ...
                break  # for nm, ...
            else:
                config['TCL_root'] = os.path.join(tclbindir, tclnm)
                config['TK_root'] = os.path.join(tclbindir, tknm)
                break
        else:
            # is_darwin
            tclbindir = os.path.dirname(fnm)
            logger.info("found TCL/TK")
            tcldir = "Tcl.framework/Resources/Scripts"
            tkdir = "Tk.framework/Resources/Scripts"
            config['TCL_root'] = "/System/Library/Frameworks/Tcl.framework/Versions/Current"
            config['TK_root'] = "/System/Library/Frameworks/Tk.framework/Versions/Current"
            break
    else:
        logger.info("could not find TCL/TK")
    if not is_win:
        dylib.exclude_list = save_exclude


def test_Crypt(config):
    # TODO: disabled for now
    config["useCrypt"] = 0
    return

    #Crypt support. We need to build the AES module and we'll use distutils
    # for that. FIXME: the day we'll use distutils for everything this will be
    # a solved problem.
    logger.info("trying to build crypt support...")
    from distutils.core import run_setup
    cwd = os.getcwd()
    args = sys.argv[:]
    try:
        os.chdir(os.path.join(HOMEPATH, "source", "crypto"))
        dist = run_setup("setup.py", ["install"])
        if dist.have_run.get("install", 0):
            config["useCrypt"] = 1
            logger.info("... crypto support available")
        else:
            config["useCrypt"] = 0
            logger.info("... error building crypto support")
    finally:
        os.chdir(cwd)
        sys.argv = args


def test_Zlib(config):
    #useZLIB
    logger.info("testing for Zlib...")
    try:
        import zlib
        config['useZLIB'] = 1
        logger.info('... Zlib available')
    except ImportError:
        config['useZLIB'] = 0
        logger.info('... Zlib unavailable')


def test_RsrcUpdate(config):
    config['hasRsrcUpdate'] = 0
    if not is_win:
        return
    # only available on windows
    logger.info("Testing for ability to set icons, version resources...")
    try:
        import win32api
        from PyInstaller.utils import icon, versioninfo
    except ImportError, detail:
        logger.info('... resource update unavailable - %s', detail)
        return

    test_exe = os.path.join(HOMEPATH, 'support', 'loader', PLATFORM, 'runw.exe')
    if not os.path.exists(test_exe):
        config['hasRsrcUpdate'] = 0
        logger.error('... resource update unavailable - %s not found', test_exe)
        return

    # The test_exe may be read-only
    # make a writable copy and test using that
    rw_test_exe = os.path.join(compat.getenv('TEMP'), 'me_test_exe.tmp')
    shutil.copyfile(test_exe, rw_test_exe)
    try:
        hexe = win32api.BeginUpdateResource(rw_test_exe, 0)
    except:
        logger.info('... resource update unavailable - win32api.BeginUpdateResource failed')
    else:
        win32api.EndUpdateResource(hexe, 1)
        config['hasRsrcUpdate'] = 1
        logger.info('... resource update available')
    os.remove(rw_test_exe)


_useUnicode = """\
# Generated by Configure.py
# This file is public domain
import %s
"""

_useUnicodeFN = os.path.join(CONFIGDIR, 'support', 'useUnicode.py')


def test_unicode(config):
    logger.info('Testing for Unicode support...')
    try:
        import codecs
        config['hasUnicode'] = 1
        try:
            import encodings
        except ImportError:
            module = "codecs"
        else:
            module = "encodings"
        _write_textfile(_useUnicodeFN, _useUnicode % module)
        logger.info('... Unicode available')
    except ImportError:
        try:
            os.remove(_useUnicodeFN)
        except OSError:
            pass
        config['hasUnicode'] = 0
        logger.info('... Unicode NOT available')


def test_UPX(config, upx_dir):
    logger.info('testing for UPX...')
    cmd = "upx"
    if upx_dir:
        cmd = os.path.normpath(os.path.join(upx_dir, cmd))

    hasUPX = 0
    try:
        vers = compat.exec_command(cmd, '-V').strip().splitlines()
        if vers:
            v = vers[0].split()[1]
            hasUPX = tuple(map(int, v.split(".")))
            if is_win and is_py24 and hasUPX < (1, 92):
                logger.error('UPX is too old! Python 2.4 under Windows requires UPX 1.92+')
                hasUPX = 0
        logger.info('...UPX %s', ('unavailable', 'available')[hasUPX != 0])
    except Exception, e:
        logger.info('...exception result in testing for UPX')
        logger.info('  %r %r', e, e.args)
    config['hasUPX'] = hasUPX
    config['upx_dir'] = upx_dir


def find_PYZ_dependencies(config):
    logger.info("computing PYZ dependencies...")
    # We need to import `archive` from `PyInstaller` directory, but
    # not from package `PyInstaller`
    import PyInstaller.loader
    a = mf.ImportTracker([
        os.path.dirname(inspect.getsourcefile(PyInstaller.loader)),
        os.path.join(HOMEPATH, 'support')])

    a.analyze_r('archive')
    mod = a.modules['archive']
    toc = build.TOC([(mod.__name__, mod.__file__, 'PYMODULE')])
    for i, (nm, fnm, typ) in enumerate(toc):
        mod = a.modules[nm]
        tmp = []
        for importednm, isdelayed, isconditional, level in mod.imports:
            if not isconditional:
                realnms = a.analyze_one(importednm, nm)
                for realnm in realnms:
                    imported = a.modules[realnm]
                    if not isinstance(imported, mf.BuiltinModule):
                        tmp.append((imported.__name__, imported.__file__, imported.typ))
        toc.extend(tmp)
    toc.reverse()
    config['PYZ_dependencies'] = toc.data


def __add_options(parser):
    """
    Add the `Configure` options to a option-parser instance or a
    option group.
    """
    parser.add_option('--upx-dir', default=None,
                      help='Directory containing UPX.')
    parser.add_option('-C', '--configfile',
                      default=DEFAULT_CONFIGFILE,
                      dest='configfilename',
                      help='Name of generated configfile (default: %default)')


def main(configfilename, upx_dir, **kw):

    if is_darwin and compat.architecture() == '64bit':
        logger.warn('You are running 64-bit Python. Created binary will not'
            ' work on Mac OS X 10.4 or 10.5. For this version it is necessary'
            ' to create 32-bit binaries.'
            ' If you need 32-bit version of Python, run Python as 32-bit binary'
            ' by command:\n\n'
            '    arch -i386 python\n')
        # wait several seconds for user to see this message
        time.sleep(4)

    try:
        config = build._load_data(configfilename)
        logger.info('read old config from %s', configfilename)
    except (IOError, SyntaxError):
        # IOerror: file not present/readable
        # SyntaxError: invalid file (platform change?)
        # if not set by Make.py we can assume Windows
        config = {'useELFEXE': 1}

    # Save Python version, to detect and avoid conflicts
    config["pythonVersion"] = sys.version
    config["pythonDebug"] = __debug__

    # Save PyInstaller path and version
    config["pyinstaller_version"] = get_version()
    config["pyinstaller_homepath"] = HOMEPATH

    find_EXE_dependencies(config)
    test_TCL_TK(config)
    test_Zlib(config)
    test_Crypt(config)
    test_RsrcUpdate(config)
    test_unicode(config)
    test_UPX(config, upx_dir)
    find_PYZ_dependencies(config)

    build._save_data(configfilename, config)
    logger.info("done generating %s", configfilename)
