#! /usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import cStringIO
import re
import os
import sys
import codecs
import string

toolset = 'v90'
end_project = '</Project>'

def _getProjects(qmake_out):
    yield os.getcwdu()
    seen = set()

    re1 = re.compile(r'^ *Reading (.*)\/.*\.pro%s?$' % '\r')
    re2 = re.compile(r'^ *Reading .*\/.*\.pro \[(.*)\]%s?$' % '\r')
    for line in cStringIO.StringIO(qmake_out):
        ma = re1.search(line)
        if not ma:
            ma = re2.search(line)

        if ma:
            normalized = os.path.normcase(ma.group(1))
            if normalized not in seen:
                seen.add(normalized)
                yield normalized

def _cleanup(lines):
    return [line.rstrip() for line in lines]

def _loadFile(path, modifier):
    return modifier(map(string.rstrip, codecs.open(path, 'r', 'gbk')))

def _saveFile(path, content):
    with codecs.open(path, 'w', 'utf-8') as f:
        f.write('\r\n'.join(content))

def _handle_by_regex(exp, targets, skipCurrentLine = True):
    compiled = re.compile(exp)
    def func(_, line):
        match = compiled.match(line)
        return (1 if skipCurrentLine else 0, (match.expand(t) for t in targets)) if match else None

    return func

def _handle_by_dict(dict):
    def func(_, line):
        return dict.get(line)

    return func

def _handle_remove_range_with_detail(filelines, exp):
    compiled = re.compile(exp);

    def func(i, line):
        match = compiled.match(line)
        if not match:
            return 0, match

        stop = filelines.index(match.expand('\\g<indent></\\g<mark>>'), i)
        return stop - i + 1, match
    return func

def _handle_remove_range(filelines, exp):
    with_detail = _handle_remove_range_with_detail(filelines, exp)

    def func(i, line):
        skip = with_detail(i, line)[0]
        return (skip, ()) if skip else None
    return func

def _handle_once(target_func):
    used = [False]

    def func(i, line):
        if used[0]:
            return None

        result = target_func(i, line)
        used[0] = result is not None
        return result

    return func

def _handle_repeat(target_func):
    def func(i, line):
        result = None
        while True:
            cur_result = target_func(i, result[1][0] if result is not None else line)
            if cur_result is not None:
                cur_result = (cur_result[0], list(cur_result[1]))

            if cur_result is None or (result is not None and result[1] == cur_result[1]):
                return result

            result = cur_result

    return func

def _moc_fix_header(filelines):
    rangeChecker = _handle_remove_range_with_detail(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+)">$')
    mocCustomBuildForMoc = re.compile(r'^(\s+)<AdditionalInputs Condition=".+">.*\moc\.exe;.*</AdditionalInputs>$')

    def func(i, line):
        skip, match = rangeChecker(i, line)
        return (skip, (match.expand('\\g<indent><ClInclude Include="\\g<file>" />'),)) if skip != 0 and mocCustomBuildForMoc.match(filelines[i + 1]) else None

    return func

def _is_qt_enabled(filelines):
    replaceDict = {}
    enabledLibs = []

    qtRe = re.compile(r'^"?%s[\\/]?(.*?)"?$' % qt_info["path_re"])
    qtLibRe = re.compile(r'^include[\\/]Qt(\w+)$')

    def filterQt(includeDir):
        match = qtRe.match(includeDir)
        if not match:
            return True

        match2 = qtLibRe.match(match.group(1))
        if match2:
            enabledLibs.append(match2.group(1))

        return False

    compiled = re.compile(r'^(\s*<AdditionalIncludeDirectories>)(.*)(</AdditionalIncludeDirectories>)$')
    for l in filter(None, (compiled.match(l) for l in filelines)):
        if l.group(0) in replaceDict:
            continue

        includeDirs = l.group(2).split(';')
        filteredIncludeDirs = filter(filterQt, includeDirs)

        replaceDict[l.group(0)] = (1, (l.group(1) + ';'.join(filteredIncludeDirs) + l.group(3),)) if len(includeDirs) != len(filteredIncludeDirs) else None

    replaceDict = {k: v for k, v in replaceDict.items() if v is not None}
    enabledLibs = set(enabledLibs)

    return (enabledLibs, replaceDict)

def _cure_vcxproj(filelines):
    def append_line(_, line):
        return (1, (line,))

    base_handler = (
        _handle_by_regex(r'^(\s*)<PropertyGroup Label="Globals">$', ('\\g<0>', '\\1  <PlatformToolset>%s</PlatformToolset>' % toolset)),
        _handle_by_regex(r'^(\s*)<ConfigurationType>DynamicLibrary</ConfigurationType>$', ('\\g<0>', '\\1<GenerateManifest>false</GenerateManifest>')),
        _handle_by_regex(r'^(\s*)<(ResourceOutputFileName)>\S+\/\$\(InputName\)(.res<\/\2>)$', ('\\1<\\2>$(OutDir)%(Filename)\\3',)),

        _handle_by_regex(r'^(\s*)<PlatformToolset>.*</PlatformToolset>$', ()),
        _handle_by_regex(r'^(\s*)<GenerateManifest>.*</GenerateManifest>$', ()),
        _handle_once(_handle_by_regex(r'^(\s*)<ItemDefinitionGroup.*>$', (
            '\\1<PropertyGroup Condition="\'$(DesignTimeBuild)\'==\'true\'">',
            '\\1  <FixPreprocessorDefinitions Condition="\'$(PlatformToolset)\'==\'v90\'">_MSC_VER=1500;_MSC_FULL_VER=150030729;__cplusplus=199711;$(FixPreprocessorDefinitions)</FixPreprocessorDefinitions>',
            '\\1</PropertyGroup>',
            '\\1<ItemDefinitionGroup Condition="\'$(FixPreprocessorDefinitions)\'!=\'\'">',
            '\\1  <ClCompile>',
            '\\1    <PreprocessorDefinitions>$(FixPreprocessorDefinitions)%(PreprocessorDefinitions)</PreprocessorDefinitions>',
            '\\1  </ClCompile>',
            '\\1  <ResourceCompile>',
            '\\1    <PreprocessorDefinitions>$(FixPreprocessorDefinitions)%(PreprocessorDefinitions)</PreprocessorDefinitions>',
            '\\1  </ResourceCompile>',
            '\\1</ItemDefinitionGroup>',
        ), False)),
    )

    enabledLibs, replaceDict = _is_qt_enabled(filelines)
    qt_handler = (
        _handle_by_regex(r'^(\s*)<Import Project="\$\(VCTargetsPath\)\\Microsoft\.Cpp\.props" />$', (
            '\\1<PropertyGroup Label="Qt">',
            '\\1  <QT_VERSION_MAJOR>%s</QT_VERSION_MAJOR>' % qt_info['major'],
            '\\1  <QT_VERSION_MINOR>%s</QT_VERSION_MINOR>' % qt_info['minor'],
            '\\1  <QT_VERSION_PATCH>%s</QT_VERSION_PATCH>' % qt_info['patch'],
            '\\1  <QTDIR>%s</QTDIR>' % qt_info['path'],
            '\\1  <QtLib>%s</QtLib>' % (';'.join(enabledLibs)),
            '\\1</PropertyGroup>',
        ), False),
        _handle_by_dict(replaceDict),
        _handle_by_regex(r'^(\s*)<ImportGroup Label="ExtensionSettings" />$', ('\\1<ImportGroup Label="ExtensionSettings">', '\\1  <Import Project="$(SolutionDir)qt4.props" />', '\\1</ImportGroup>')),
        _handle_by_regex(r'^(\s*)<ImportGroup Label="ExtensionTargets" />$', ('\\1<ImportGroup Label="ExtensionTargets">', '\\1  <Import Project="$(SolutionDir)qt4.targets" />', '\\1</ImportGroup>')),
        _handle_repeat(_handle_by_regex(r'^(\s*<PreprocessorDefinitions)(>|.*?;)(QT_[A-Z]+_LIB;|QT_DLL;|QT_NO_DEBUG;)+(.*</PreprocessorDefinitions>)$', ('\\1\\2\\4',))),
        _handle_repeat(_handle_by_regex(r'^(\s*<AdditionalDependencies)(>|.*?;)(%s[\\/]lib[\\/]Qt\w+\.lib;)+(.*</AdditionalDependencies>)$' % qt_info["path_re"], ('\\1\\2\\4',))),
        _handle_by_regex(r'^(\s*<AdditionalLibraryDirectories)(>|.*?;)(%s[\\/]lib;)+(.*</AdditionalLibraryDirectories>)$' % qt_info["path_re"], ('\\1\\2\\4',)),

        _moc_fix_header(filelines),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\moc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+\\.+.moc)">$'),
    ) if enabledLibs else ()

    handlers = base_handler + qt_handler + (append_line, )

    ret = []
    skip = 0
    for i in xrange(0, len(filelines)):
        if skip == 0:
            for h in handlers:
                result = h(i, filelines[i])
                if result is not None:
                    skip, lines = result
                    ret += lines
                    if skip != 0:
                        break;

        skip = skip - 1

    return ret

def _cure_vcxproj_filters(filelines):
    return filelines

def _cure_sln(filelines):
    projs = {'.': [], '..': 0}

    regexpProject = re.compile(r'Project\("(?P<project_guid>{[0-9A-F-]+})"\) = "(?P<project_name>[^"]+)", "(?P<project_path>[^"]+)", "(?P<node_guid>{[0-9A-F-]+})"')

    for i in xrange(0, len(filelines)):
        match = regexpProject.match(filelines[i])
        if match:
            projDict = match.groupdict()
            curLevel = projs
            for p in projDict['project_path'].split('\\')[:-1]:
                curLevel['..'] += 1
                curLevel.setdefault(p, {'.': [], '..': 0})
                curLevel = curLevel[p]
            curLevel['..'] += 1
            curLevel['.'].append(projDict)

    return ['Microsoft Visual Studio Solution File, Format Version 12.00', '# Visual Studio Version 16'] + [line for line in filelines][2:]

def _cure_path(path):
    doctors = (
        ('.vcxproj', _cure_vcxproj),
        ('.vcxproj.filters', _cure_vcxproj_filters),
        ('.sln', _cure_sln),
    )
    for root, _, files in os.walk(path):
        for f in files:
            for s, p in doctors:
                if f.endswith(s):
                    fp = os.path.join(root, f)
                    print 'Curing ' + fp
                    _saveFile(fp, _loadFile(fp, p))
                    break
        break

def _qt_info():
    process = subprocess.Popen(['qmake', '-v'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    match = re.compile(r'^Using Qt version (?P<major>\d+).(?P<minor>\d+).(?P<patch>\d+) in (?P<path>.*?)([/\\]lib)?$').match(process.communicate()[0].splitlines(False)[1])
    if match:
        print match.group(0)
        qt_info = match.groupdict()
        qt_info["path_re"] = "[%s%s]%s" % (qt_info['path'][0].lower(), qt_info['path'][0].upper(), qt_info['path'][1:].replace('\\', '/').replace('/', r"[/\\]"))
        return qt_info
    else:
        raise Exception('Can\'t detect Qt version')

def main():
    global qt_info
    qt_info = _qt_info()

    global toolset
    subarg = 1
    if len(sys.argv) > 1:
        if sys.argv[1].startswith("--"):
            toolset = sys.argv[1][2:]
            subarg = 2

    command_list = ['qmake', '-tp', 'vc', '-r', '-spec', 'win32-msvc2010'] + sys.argv[subarg:]

    print u'Running qmake @ ' + os.getcwdu()
    process = subprocess.Popen(
        command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    for proj in _getProjects(process.communicate()[0]):
        _cure_path(proj)

if __name__ == '__main__':
    main()

