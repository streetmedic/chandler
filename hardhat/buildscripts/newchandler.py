
#   Copyright (c) 2003-2006 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.


# Chandler blueprint for new build process

"""
Notes:
Start() is responsible for capturing all pertinent output to the open file
object, log.  True is returned if a new build was created, False is returned
if no code has changed, and an exception is raised if there are problems.
"""

# To appease older Pythons:
True = 1
False = 0


import os, hardhatutil, hardhatlib, sys, re, glob

path     = os.environ.get('PATH', os.environ.get('path'))
whereAmI = os.path.dirname(os.path.abspath(hardhatlib.__file__))

svnProgram   = hardhatutil.findInPath(path, "svn")
treeName     = "Chandler"
sleepMinutes = 5
logPath      = 'hardhat.log'
separator    = "- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -\n"

reposRoot    = 'http://svn.osafoundation.org/chandler'
reposModules = ['chandler', 'internal/installers']
mainModule   = reposModules[0]

def Start(hardhatScript, workingDir, buildVersion, clobber, log, skipTests=False, upload=False, branchID=None, revID=None):

    global buildenv, changes

    try:
        buildenv = hardhatlib.defaults
        buildenv['root'] = workingDir
        buildenv['hardhatroot'] = whereAmI
        hardhatlib.init(buildenv)

    except hardhatlib.HardHatMissingCompilerError:
        print "Could not locate compiler.  Exiting."
        sys.exit(1)

    except hardhatlib.HardHatUnknownPlatformError:
        print "Unsupported platform, '" + os.name + "'.  Exiting."
        sys.exit(1)

    except hardhatlib.HardHatRegistryError:
        print
        print "Sorry, I am not able to read the windows registry to find" 
        print "the necessary VisualStudio complier settings.  Most likely you"
        print "are running the Cygwin python, which will hopefully be supported"
        print "soon.  Please download a windows version of python from:\n"
        print "http://www.python.org/download/"
        print
        sys.exit(1)

    except Exception, e:
        print "Could not initialize hardhat environment.  Exiting."
        print "Exception:", e
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # if branchID is present then we have to modify reposBase as a branch has
    # been requested instead of the trunk
    if branchID:
        reposBase='tags/%s' % branchID
    else:
        reposBase='trunk'

    # make sure workingDir is absolute
    workingDir = os.path.abspath(workingDir)
    chanDir = os.path.join(workingDir, mainModule)
    # test if we've been thruough the loop at least once
    if clobber == 1:
        if os.path.exists(chanDir):
            hardhatutil.rmdirRecursive(chanDir)

    os.chdir(workingDir)

    # remove outputDir and create it
    outputDir = os.path.join(workingDir, "output")
    if os.path.exists(outputDir):
        hardhatutil.rmdirRecursive(outputDir)
    os.mkdir(outputDir)

    buildVersionEscaped = "\'" + buildVersion + "\'"
    buildVersionEscaped = buildVersionEscaped.replace(" ", "|")

    buildModes = ('debug', 'release')

    revisions = {}

    if not os.path.exists(chanDir):
        # Initialize sources
        print "Setup source tree..."
        log.write("- - - - tree setup - - - - - - -\n")

        print reposModules
        for module in reposModules:
            svnSource = os.path.join(reposRoot, reposBase, module)

            log.write("[tbox] Retrieving source tree [%s]\n" % svnSource)

            # if revID is present then we have to modify the request to include
            # the given revision #
            if revID:
                cmd = [svnProgram, "co", "-r %s" % revID, svnSource, module]
            else:
                cmd = [svnProgram, "co", svnSource, module]

            outputList = hardhatutil.executeCommandReturnOutputRetry(cmd)

            revisions[module] = determineRevision(outputList)

            hardhatutil.dumpOutputList(outputList, log)

        os.chdir(chanDir)

        for releaseMode in buildModes:
            doInstall(releaseMode, workingDir, log)

            doDistribution(releaseMode, workingDir, log, outputDir, buildVersion, buildVersionEscaped, hardhatScript)

            if skipTests:
                ret = 'success'
            else:
                ret = doTests(hardhatScript, releaseMode, workingDir,
                              outputDir, buildVersion, log)
                if ret != 'success':
                    break

                ret = doFunctionalTests(releaseMode, workingDir, log)
                if ret != 'success':
                    break

        changes = "-first-run"
    else:
        os.chdir(chanDir)

        print "Checking SVN for updates"
        log.write("Checking SVN for updates\n")

        (svnChanges, revisions['chandler']) = changesInSVN(chanDir, workingDir, log, revID)

        if svnChanges:
            log.write("Changes in SVN require install\n")
            changes = "-changes"
            for releaseMode in buildModes:
                doInstall(releaseMode, workingDir, log)

        if svnChanges:
            log.write("Changes in SVN require making distributions\n")
            changes = "-changes"
            for releaseMode in buildModes:
                doDistribution(releaseMode, workingDir, log, outputDir,
                               buildVersion, buildVersionEscaped, hardhatScript)

        if not svnChanges:
            log.write("No changes\n")
            changes = "-nochanges"

        # do tests
        if skipTests:
            ret = 'success'
        else:
            for releaseMode in buildModes:
                ret = doTests(hardhatScript, releaseMode, workingDir,
                              outputDir, buildVersion, log)
                if ret != 'success':
                    break

                ret = doFunctionalTests(releaseMode, workingDir, log)
                if ret != 'success':
                    break

    return (ret + changes, revisions['chandler'])


def doTests(hardhatScript, mode, workingDir, outputDir, buildVersion, log):
    testDir = os.path.join(workingDir, "chandler")
    os.chdir(testDir)

    try:
        print "Testing " + mode
        log.write(separator)
        log.write("Testing " + mode + " ...\n")

        cmd = ['./tools/do_tests.sh', '-u', '-m %s' % mode]

        outputList = hardhatutil.executeCommandReturnOutput(cmd)

        hardhatutil.dumpOutputList(outputList, log)

    except Exception, e:
        print "a testing error", e
        doCopyLog("***Error during tests***", workingDir, logPath, log)
        forceBuildNextCycle(log, workingDir)
        return "test_failed"
    else:
        doCopyLog("Tests successful", workingDir, logPath, log)

    return "success"  # end of doTests( )


def dumpTestLogs(log, chandlerLog, FuncTestLog, exitCode=0):
    if FuncTestLog:
        log.write("FunctionalTestSuite.log:\n")
        try:
            CopyLog(FuncTestLog, log)
        except:
            pass
        log.write(separator)

    if chandlerLog:
        log.write("chandler.log:\n")
        try:
            CopyLog(chandlerLog, log)
        except:
            pass
        log.write(separator)

    log.write("exit code=%s\n" % exitCode)
    log.write("NOTE: If the tests themselves passed but the exit code\n")
    log.write("      reports failure, it means a shutdown problem.\n")


def doFunctionalTests(releaseMode, workingDir, log):
    chandlerDir = os.path.join(workingDir,  'chandler')
    logDir      = os.path.join(chandlerDir, 'test_profile')
    chandlerLog = os.path.join(logDir,      'chandler.log')
    FuncTestLog = os.path.join(logDir,      'FunctionalTestSuite.log')

    if buildenv['os'] == 'win':
        runChandler = 'RunChandler.bat'
    else:
        runChandler = 'RunChandler'

    if releaseMode == 'debug':
        runChandler = os.path.join(chandlerDir, 'debug', runChandler)
    elif releaseMode == 'release':
        runChandler = os.path.join(chandlerDir, 'release', runChandler)

    os.chdir(chandlerDir)

    try:
        print "Running %s Functional Tests" % releaseMode
        log.write(separator)
        log.write("Running %s Functional Tests ...\n" % releaseMode)

        try:
            os.remove(chandlerLog)
        except OSError:
            pass

        args = [runChandler,
                '--create', '--nocatch',
                '--profileDir=%s' % logDir,
                '--parcelPath=tools/QATestScripts/DataFiles',
                '--scriptTimeout=600', 
                '--scriptFile=tools/cats/Functional/FunctionalTestSuite.py',
                '--chandlerTestLogfile=FunctionalTestSuite.log', #new framework defaults to no log without this
                '--chandlerTestDebug=1',
                '--chandlerTestMask=0',]

        outputList = hardhatutil.executeCommandReturnOutput(args)

        hardhatutil.dumpOutputList(outputList, log)

        dumpTestLogs(log, chandlerLog, FuncTestLog)

        for line in outputList:
            if line.find('#TINDERBOX# Status = FAIL') >= 0 or \
               line.find('#TINDERBOX# Status = UNCHECKED') >= 0:
                print "functional tests failed"
                log.write("***Error during functional tests***\n")

                forceBuildNextCycle(log, workingDir)

                return "test_failed"

    except hardhatutil.ExternalCommandErrorWithOutputList, e:
        dumpTestLogs(log, chandlerLog, FuncTestLog, e.args)

        print "functional tests failed", e
        log.write("***Error during functional tests***\n")

        forceBuildNextCycle(log, workingDir)

        return "test_failed"

    except Exception, e:
        print "functional tests failed", e
        log.write("***Error during functional tests***\n")
        log.write("Exception:\n")
        log.write(str(e) + "\n")

        forceBuildNextCycle(log, workingDir)

        return "test_failed"

    else:
        log.write("Functional tests exit code=0\n")

    return "success"


def doPerformanceTests(hardhatScript, mode, workingDir, outputDir, buildVersion, log):
    chandlerDir = os.path.join(workingDir, "chandler")
    testDir     = os.path.join(chandlerDir, 'tools', 'QATestScripts', 'Performance')
    logDir      = os.path.join(chandlerDir, 'test_profile')
    chandlerLog = os.path.join(logDir,      'chandler.log')
    FuncTestLog = os.path.join(logDir,      'FunctionalTestSuite.log')

    if buildenv['version'] == 'debug':
        python = buildenv['python_d']
        pythonOpts = ''
    elif buildenv['version'] == 'release':
        python = buildenv['python']
        pythonOpts = '-O'

    os.chdir(chandlerDir)

    result = 'success'

    testFiles = glob.glob(os.path.join(testDir, 'Perf*.py'))

    for testFile in testFiles:
        args = [python, pythonOpts, os.path.join(chandlerDir, 'Chandler.py'),
                '--create', '--profileDir=%s' % logDir, '--scriptFile=%s' % testFile]

        try:
            try:
                os.remove('chandler.log')
            except OSError:
                pass

            outputlist = hardhatutil.executeCommandReturnOutput(args)

            # Hack: find if any line contains '#TINDERBOX# Status = FAILED' and
            # if so raise the exception to signal test failure
            for line in outputList:
                if line.find('#TINDERBOX# Status = FAIL') >= 0 or \
                   line.find('#TINDERBOX# Status = UNCHECKED') >= 0:
                    raise hardhatutil.ExternalCommandErrorWithOutputList([0, outputList])

            hardhatutil.dumpOutputList(outputlist, log)

        except hardhatutil.ExternalCommandErrorWithOutputList, e:
            print "perf tests failed", e
            log.write("***Error during performance tests***\n")
            log.write("Test log:\n")
            hardhatutil.dumpOutputList(e.outputList, log)
            log.write("exit code=%s\n" % e.args)
            log.write("NOTE: If the tests themselves passed but the exit code\n")
            log.write("      reports failure, it means a shutdown problem.\n")
            log.write("chandler.log:\n")
            try:
                CopyLog(chandlerLog, log)
            except:
                pass
            forceBuildNextCycle(log, workingDir)
            return "test_failed"
        except Exception, e:
            print "perf tests failed", e
            log.write("***Error during performance tests***\n")
            log.write("Exception:\n")
            log.write(str(e) + "\n")
            forceBuildNextCycle(log, workingDir)
            return "test_failed"
        else:
            log.write("Performance tests exit code=0\n")

    return result


def doDistribution(releaseMode, workingDir, log, outputDir, buildVersion, buildVersionEscaped, hardhatScript):
    #   Create end-user, developer distributions
    print "Making distribution files for " + releaseMode
    log.write(separator)
    log.write("Making distribution files for " + releaseMode + "\n")
    if releaseMode == "debug":
        distOption = "-dD"
    else:
        distOption = "-D"

    try:
        outputList = hardhatutil.executeCommandReturnOutput(
         [hardhatScript, "-o", os.path.join(outputDir, buildVersion), distOption, buildVersionEscaped])
        hardhatutil.dumpOutputList(outputList, log)
    except Exception, e:
        doCopyLog("***Error during distribution building*** ", workingDir, logPath, log)
        forceBuildNextCycle(log, workingDir)
        raise e


def doCopyLog(msg, workingDir, logPath, log):
    # hardhat scripts should leave harhat.log behind both on success and
    # failure (barring catastrophic failure), so we can copy that into the
    # build log
    log.write(msg + "\n")
    log.write(separator)
    logPath = os.path.join(workingDir, logPath)
    log.write("Contents of " + logPath + ":\n")
    if os.path.exists(logPath):
        CopyLog(logPath, log)
    else:
        log.write(logPath + ' does not exist!\n')
    log.write(separator)


def determineRevision(outputList):
    """
    Scan output of svn up command and extract the revision #
    """
    revision = ""

    for line in outputList:
        s = line.lower()

          # handle "Update to revision ####." - svn up
        if s.find("updated to revision") != -1:
            revision = s[19:-2]
            break
          # handle "At revision ####." - svn up
        if s.find("at revision") != -1:
            revision = s[12:-2]
            break
          # handler "Checked out revision ####." - svn co
        if s.find("checked out revision") != -1:
            revision = s[21:-2]
            break

    return revision

def changesInSVN(moduleDir, workingDir, log, revID=None):
    changesAtAll = False
    svnRevision  = ""

    for module in reposModules:
        log.write("[tbox] Checking for updates [%s] [%s]\n" % (workingDir, module))

        moduleDir = os.path.join(workingDir, module)

        print "[%s] [%s] [%s]" % (workingDir, module, moduleDir)
        os.chdir(moduleDir)

        # if revID is present then we have to modify the request to include
        # the given revision #
        if revID:
            cmd = [svnProgram, "up", "-r %s" % revID]
        else:
            cmd = [svnProgram, "up"]

        outputList = hardhatutil.executeCommandReturnOutputRetry(cmd)

        svnRevision = determineRevision(outputList)

        hardhatutil.dumpOutputList(outputList, log) 

        if NeedsUpdate(outputList):
            changesAtAll = True
            print "" + module + " needs updating"
        else:
            # print "NO, unchanged"
            log.write("Module unchanged" + "\n")

    log.write(separator)
    log.write("Done with SVN\n")

    return (changesAtAll, svnRevision)


def doInstall(buildmode, workingDir, log, cleanFirst=False):
    # for our purposes, we do not really do a build
    # we will update chandler from SVN, and grab new tarballs when they appear
    if buildmode == "debug":
        dbgStr = "DEBUG=1"
    else:
        dbgStr = ""

    if cleanFirst:
        clean = " clean "
    else:
        clean = " "

    moduleDir = os.path.join(workingDir, mainModule)
    os.chdir(moduleDir)

    targets = ['distrib', 'strip', 'purge']

    print "Doing make " + dbgStr + clean + " ".join(targets) + "\n"
    log.write("Doing make " + dbgStr + clean + " ".join(targets) + "\n")

    try:
        cmd = [buildenv['make'], dbgStr, clean]
        cmd += targets

        outputList = hardhatutil.executeCommandReturnOutput(cmd)

        hardhatutil.dumpOutputList(outputList, log)
    except hardhatutil.ExternalCommandErrorWithOutputList, e:
        print "build error"
        log.write("***Error during build***\n")
        log.write(separator)
        log.write("Build log:" + "\n")
        hardhatutil.dumpOutputList(e.outputList, log)
        log.write(separator)
        forceBuildNextCycle(log, workingDir)
        raise e
    except Exception, e:
        print "build error"
        log.write("***Error during build***\n")
        log.write(separator)
        log.write("Exception:\n")
        log.write(str(e) + "\n")
        log.write(separator)
        forceBuildNextCycle(log, workingDir)
        raise e


def forceBuildNextCycle(log, workingDir):
    doRealclean(log, workingDir)
    # We trigger build for next cycle by removing /chandler/Makefile,
    # which will be noticed as an 'update' in the beginning of next
    # cycle which will cause doInstall etc. to be called.
    print 'Removing chandler/Makefile to trigger build next cycle'
    log.write('Removing chandler/Makefile to trigger build next cycle\n')
    chandlerMakefile = os.path.join(workingDir, mainModule, 'Makefile')
    if os.path.exists(chandlerMakefile):
        os.remove(chandlerMakefile)


def doRealclean(log, workingDir):
    try:
        # If make install fails, it will almost certainly fail next time
        # as well - the typical case has been bad binaries packages.
        # So what we do here is try to do realclean which will force
        # the build to get new binaries tarballs next time, and if fixed
        # binaries were uploaded in the meanwhile we'll recover
        # automatically. This will also sort us out of corrupted debug/release.
        print "Doing make realclean\n"
        log.write("Doing make realclean\n")
        moduleDir = os.path.join(workingDir, mainModule)
        os.chdir(moduleDir)
        outputList = hardhatutil.executeCommandReturnOutput(
         [buildenv['make'], "realclean"])
        hardhatutil.dumpOutputList(outputList, log)
    except:
        print "make realclean failed\n"
        log.write("make realclean failed\n")

def NeedsUpdate(outputList):
    for line in outputList:
        if line.lower().startswith('at revision'):
            # used to prevent the message that SVN produces when
            # nothing was updated from tripping the 'A' check below
            continue
        if line.lower().find("ide scripts") != -1:
            # this hack is for skipping some Mac-specific files that
            # under Windows always appear to be needing an update
            continue
        if line.lower().find("xercessamples") != -1:
            # same type of hack as above
            continue
        if line.lower().startswith('restored'):
            # treat a restored file as if it is a modified file
            print "needs update because of", line
            return True

        s = line[:4]  # in subversion, there are 3 possible positions
                      # the update flags are found

        if s.find("U") != -1:
            print "needs update because of", line
            return True
        if s.find("P") != -1:
            print "needs update because of", line
            return True
        if s.find("A") != -1:
            print "needs update because of", line
            return True
        if s.find("G") != -1:
            print "needs update because of", line
            return True
        if s.find("!") != -1:
            print "needs update because of", line
            return True
    return False

def CopyLog(file, fd):
    input = open(file, "r")
    line = input.readline()
    while line:
        fd.write(line)
        line = input.readline()
    input.close()

def getVersion(fileToRead):
    input = open(fileToRead, "r")
    line = input.readline()
    while line:
        if line == "\n":
            line = input.readline()
            continue
        else:
            m=re.match('VERSION=(.*)', line)
            if not m == 'None' or m == 'NoneType':
                version = m.group(1)
                input.close()
                return version

        line = input.readline()
    input.close()
    return 'No Version'

