#! /usr/bin/env python
# -*- coding: utf-8 -*-

import subprocess
import cStringIO
import re
import os
import sys
import codecs
import string
import uuid
import signal
import tempfile
import shutil

end_project = '</Project>'

class GlobalInfo:
    major = 0
    minor = 0
    patch = 0
    path = ""
    path_re = ""
    temp_mkspec = ""
    platformToolset = ""
    MSC_VER = 0
    MSC_FULL_VER = 0

globalInfo = GlobalInfo()

def _getProjects(qmake_out):
    cwd = os.path.normcase(os.path.normpath(os.getcwd()))
    seen = set([cwd])
    yield cwd

    re1 = re.compile(r'^ *Reading (.*)\/.*\.pro%s?$' % '\r')
    re2 = re.compile(r'^ *Reading .*\/.*\.pro \[(.*)\]%s?$' % '\r')
    for line in cStringIO.StringIO(qmake_out):
        ma = re1.search(line)
        if not ma:
            ma = re2.search(line)

        if ma:
            normalized = os.path.normcase(os.path.normpath(ma.group(1)))
            if normalized not in seen:
                seen.add(normalized)
                yield normalized

def _loadFile(path, modifier, out):
    return modifier(map(string.rstrip, codecs.open(path, 'r', 'gbk')), path, out)

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

def _handle_list(list_exp, handlers, sep = ';'):
    compiled = re.compile(list_exp)

    def func(_, line):
        match = compiled.match(line)
        old_list = match.group('list') if match else None
        if not old_list:
            return None

        new_list = _execute_handler_alllines(old_list.split(sep), handlers + (append_line,))
        return (1, (line.replace(old_list, sep.join(new_list), 1),))

    return func

def _execute_handler(i, line, handlers):
    skip = 0
    retLines = []

    for h in handlers:
        ret = h(i, line)
        if ret is not None:
            skip, lines = ret
            retLines += lines
            if skip != 0:
                break;

    return (skip, retLines) if skip != 0 or len(retLines) > 0 else None

def _execute_handler_alllines(filelines, handlers):
    ret = []
    skip = 0
    for i in xrange(0, len(filelines)):
        if skip == 0:
            skip, lines = _execute_handler(i, filelines[i], handlers)
            ret += lines

        skip = skip - 1

    return ret

def _handle_custom_build(filelines):
    moreHandler = []

    _generate_precompiled_header_source = []

    clCompileRangeChecker = _handle_remove_range_with_detail(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+)">$')
    precompiledHeaderSourceChecker = re.compile(r'^(\s+)<PrecompiledHeader Condition=".*">Create</PrecompiledHeader>$')
    def _handle_generate_precompiled_header_source(i, line):
        if line == end_project:
            return (0, (
                '  <PropertyGroup>',
                '    <BeforeClCompileTargets>',
                '      $(BeforeClCompileTargets);',
                '      _GeneratePrecompiledHeaderSource;',
                '    </BeforeClCompileTargets>',
                '    <CppCleanDependsOn>',
                '      _GeneratePrecompiledHeaderSource_Clean;',
                '      $(CppCleanDependsOn);',
                '    </CppCleanDependsOn>',
                '  </PropertyGroup>',
                '  <Target Name="_GeneratePrecompiledHeaderSource"',
                '          DependsOnTargets="_GeneratePrecompiledHeaderSource_Filter;_GeneratePrecompiledHeaderSource_Create" />',
                '  <Target Name="_GeneratePrecompiledHeaderSource_Filter">',
                '    <ItemGroup>',
                '      <PrecompiledHeaderSource Include="@(ClInclude)" Condition="\'%(ClInclude.PrecompiledHeader)\' == \'Create\'">',
                '        <PrecompiledHeaderSourceFile>$(IntDir)%(Filename)%(Extension)$(DefaultLanguageSourceExtension)</PrecompiledHeaderSourceFile>',
                '      </PrecompiledHeaderSource>',
                '      <ClCompile Include="@(PrecompiledHeaderSource->\'%(PrecompiledHeaderSourceFile)\')" />',
                '    </ItemGroup>',
                '  </Target>',
                '  <Target Name="_GeneratePrecompiledHeaderSource_Create"',
                '          Inputs="@(PrecompiledHeaderSource)"',
                '          Outputs="%(PrecompiledHeaderSource.PrecompiledHeaderSourceFile)">',
                '    <ItemGroup>',
                '      <PrecompiledHeaderSourceContent Include="/%2A--------------------------------------------------------------------" />',
                '      <PrecompiledHeaderSourceContent Include="%2A Precompiled header source file used by Visual Studio.NET to generate" />',
                '      <PrecompiledHeaderSourceContent Include="%2A the .pch file." />',
                '      <PrecompiledHeaderSourceContent Include="%2A" />',
                '      <PrecompiledHeaderSourceContent Include="%2A Due to issues with the dependencies checker within the IDE, it" />',
                '      <PrecompiledHeaderSourceContent Include="%2A sometimes fails to recompile the PCH file, if we force the IDE to" />',
                '      <PrecompiledHeaderSourceContent Include="%2A create the PCH file directly from the header file." />',
                '      <PrecompiledHeaderSourceContent Include="%2A" />',
                '      <PrecompiledHeaderSourceContent Include="%2A This file is auto-generated by qmake since no PRECOMPILED_SOURCE was" />',
                '      <PrecompiledHeaderSourceContent Include="%2A specified, and is used as the common stdafx.cpp. The file is only" />',
                '      <PrecompiledHeaderSourceContent Include="%2A generated when creating .vcxproj project files, and is not used for" />',
                '      <PrecompiledHeaderSourceContent Include="%2A command line compilations by nmake." />',
                '      <PrecompiledHeaderSourceContent Include="%2A" />',
                '      <PrecompiledHeaderSourceContent Include="%2A WARNING: All changes made in this file will be lost." />',
                '      <PrecompiledHeaderSourceContent Include="--------------------------------------------------------------------%2A/" />',
                '      <PrecompiledHeaderSourceContent Include="#include &quot;$([MSBuild]::MakeRelative($(ProjectDir)$(IntDir), $(ProjectDir)%(PrecompiledHeaderSource.Identity)))&quot;" />',
                '    </ItemGroup>',
                '    <WriteLinesToFile File="%(PrecompiledHeaderSource.PrecompiledHeaderSourceFile)"',
                '                      Lines="@(PrecompiledHeaderSourceContent)"',
                '                      Overwrite="true" />',
                '    <ItemGroup>',
                '      <PrecompiledHeaderSourceContent Remove="@(PrecompiledHeaderSourceContent)" />',
                '    </ItemGroup>',
                '  </Target>',
                '  <Target Name="_GeneratePrecompiledHeaderSource_Clean" DependsOnTargets="_GeneratePrecompiledHeaderSource_Filter">',
                '    <Delete Files="@(PrecompiledHeaderSource->\'%(PrecompiledHeaderSourceFile)\')" />',
                '  </Target>',
            ))

        skip, match = clCompileRangeChecker(i, line)
        return (skip, ()) if skip > 4 and precompiledHeaderSourceChecker.match(filelines[i + 3]) else None

    def _mark_generate_precompiled_header_source(i, line):
        if not _generate_precompiled_header_source:
            _generate_precompiled_header_source.append(True)
            moreHandler.append(_handle_generate_precompiled_header_source)

    rangeChecker = _handle_remove_range_with_detail(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+)">$')
    customBuildHandler = (
        (2, re.compile(r'^(\s+)<AdditionalInputs Condition=".+">.*rcc\.exe;.*</AdditionalInputs>$'), ('\\g<indent><QtQrc Include="\\g<file>" />',), None),
        (1, re.compile(r'^(\s+)<AdditionalInputs Condition=".+">.*moc\.exe;.*</AdditionalInputs>$'), ('\\g<indent><ClInclude Include="\\g<file>" />',), None),
        (2, re.compile(r'^(\s+)<Message Condition=".+">Generating precompiled header source file.*</Message>$'), (
            '\\g<indent><ClInclude Include="\\g<file>">',
            '\\g<indent>  <PrecompiledHeader>Create</PrecompiledHeader>',
            '\\g<indent></ClInclude>',
        ), _mark_generate_precompiled_header_source),
    )

    def func(i, line):
        skip, match = rangeChecker(i, line)
        if skip != 0:
            for h in customBuildHandler:
                offset, rule, replacement, f = h
                if rule.match(filelines[i + offset]):
                    if f:
                        f(i, line)

                    return (skip, (match.expand(t) for t in replacement))

        return _execute_handler(i, line, moreHandler)

    return func

def _is_qt_enabled(filelines):
    replaceDict = {}
    enabledLibs = []

    qtRe = re.compile(r'^"?%s[\\/]?(.*?)"?$' % globalInfo.path_re)
    qtLibRe = re.compile(r'^include[\\/]Qt(\w+)$')

    def filterQt(includeDir):
        match = qtRe.match(includeDir)
        if match:
            match2 = qtLibRe.match(match.group(1))
            if match2:
                enabledLibs.append(match2.group(1))

            return False
        elif includeDir == globalInfo.temp_mkspec:
            return False

        return True

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

def append_line(_, line):
    return (1, (line,))

def eat_line(_, line):
    return (1, ())

def _cure_vcxproj(filelines, path, out):
    enabledLibs, replaceDict = _is_qt_enabled(filelines)

    base_handler = (
        _handle_by_regex(r'^(\s*)<PropertyGroup Label="Globals">$', ('\\g<0>', '\\1  <PlatformToolset>%s</PlatformToolset>' % globalInfo.platformToolset)),
        _handle_by_regex(r'^(\s*)<ConfigurationType>DynamicLibrary</ConfigurationType>$', ('\\g<0>', '\\1<GenerateManifest>false</GenerateManifest>')),
        _handle_by_regex(r'^(\s*)<(ResourceOutputFileName)>\S+\/\$\(InputName\)(.res<\/\2>)$', ('\\1<\\2>$(OutDir)$(ProjectName)\\3',)),

        _handle_by_regex(r'^(\s*)<PlatformToolset>.*</PlatformToolset>$', ()),
        _handle_by_regex(r'^(\s*)<GenerateManifest>.*</GenerateManifest>$', ()),
        _handle_once(_handle_by_regex(r'^(\s*)<ItemDefinitionGroup.*>$', (
            '\\1<PropertyGroup Condition="\'$(DesignTimeBuild)\'==\'true\'">',
            '\\1  <FixPreprocessorDefinitions>_MSC_VER=%d;_MSC_FULL_VER=%d;%s$(FixPreprocessorDefinitions)</FixPreprocessorDefinitions>' % (globalInfo.MSC_VER, globalInfo.MSC_FULL_VER, "__cplusplus=199711L;" if globalInfo.MSC_VER < 1900 else ""),
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

        _handle_custom_build(filelines),
        _handle_by_regex(r'^(\s*)<(\S+)(.*)>(.*)\$\(NOINHERIT\)(.*)</\2>$', ('\\1<\\2\\3>\\4\\5</\\2>',)),
        _handle_by_regex(r'^(\s*)<(\S+)(.*)>(.*)\$\(INHERIT\)(.*)</\2>$', ('\\1<\\2\\3>\\4%(\\2)\\5</\\2>',)),
        _handle_by_dict(replaceDict),
    )

    rel_to_this_path = os.path.relpath(os.path.dirname(__file__), os.path.dirname(out))

    qt_handler = (
        _handle_by_regex(r'^(\s*)<Import Project="\$\(VCTargetsPath\)\\Microsoft\.Cpp\.props" />$', (
            '\\1<PropertyGroup Label="Qt">',
            '\\1  <QT_VERSION_MAJOR>%s</QT_VERSION_MAJOR>' % globalInfo.major,
            '\\1  <QT_VERSION_MINOR>%s</QT_VERSION_MINOR>' % globalInfo.minor,
            '\\1  <QT_VERSION_PATCH>%s</QT_VERSION_PATCH>' % globalInfo.patch,
            '\\1  <QTDIR>%s</QTDIR>' % globalInfo.path.replace('\\', '\\\\'),
            '\\1  <QtLib>%s</QtLib>' % (';'.join(enabledLibs)),
            '\\1</PropertyGroup>',
        ), False),
        _handle_by_regex(r'^(\s*)<ImportGroup Label="ExtensionSettings" />$', ('\\1<ImportGroup Label="ExtensionSettings">', '\\1  <Import Project="%s" />' % os.path.join(rel_to_this_path, "qt4.props").replace('\\', '\\\\'), '\\1</ImportGroup>')),
        _handle_by_regex(r'^(\s*)<ImportGroup Label="ExtensionTargets" />$', ('\\1<ImportGroup Label="ExtensionTargets">', '\\1  <Import Project="%s" />' % os.path.join(rel_to_this_path, "qt4.targets").replace('\\', '\\\\'), '\\1</ImportGroup>')),
        _handle_list(r'^\s*<PreprocessorDefinitions>(?P<list>.*)</PreprocessorDefinitions>$', (_handle_by_regex(r'QT_([A-Z]+_LIB|DLL|NO_DEBUG)', ()),)),
        _handle_list(r'^\s*<AdditionalDependencies>(?P<list>.*)</AdditionalDependencies>$', (_handle_by_regex(r'%s[\\/]lib[\\/]Qt\w+\.lib' % globalInfo.path_re, ()),)),
        _handle_by_regex(r'^(\s*<AdditionalLibraryDirectories)(>|.*?;)(%s[\\/]lib;)+(.*</AdditionalLibraryDirectories>)$' % globalInfo.path_re, ('\\1\\2\\4',)),

        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\qrc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\moc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+\\.+.moc)">$'),
    ) if enabledLibs else ()

    handlers = base_handler + qt_handler + (append_line, )

    return _execute_handler_alllines(filelines, handlers)

def _cure_vcxproj_filters(filelines, path, out):
    return filelines

def _cure_sln(filelines, path, out):
    projs = {}

    current_handler = [None]

    def global_wrap_handler(second_handler, custom_end_line_handler = append_line):
        def func(i, line):
            if line.endswith('EndGlobalSection'):
                current_handler[0] = global_handler
                return custom_end_line_handler(i, line)
            return second_handler(i, line)

        return func

    def global_remove_handler(i, line):
        current_handler[0] = global_wrap_handler(eat_line, eat_line)

        return eat_line(i, line)

    def global_SolutionConfiguration_preSolution_handler(i, line):
        h = _handle_by_regex(r'^(\s+)(.+) = (.+)$', ('\\1\\3 = \\3',))
        def func(i, line):
            return h(i, line)
            #return h(i, line.replace('Win32', 'x86'))

        current_handler[0] = global_wrap_handler(func)

        return (1, ('\tGlobalSection(SolutionConfigurationPlatforms) = preSolution',))

    def global_ProjectDependencies_postSolution_handler(i, line):
        regexp = re.compile(r'^(\s*)({[0-9A-F-]+})\.\d+ = ({[0-9A-F-]+})$')
        def func(i, line):
            match = regexp.match(line)
            if match:
                proj = projs.get(match.group(2))
                dep = projs.get(match.group(3))
                if proj and dep:
                    proj['project_dependencies'].append(dep)

            return eat_line(i, line)

        current_handler[0] = global_wrap_handler(func, eat_line)

        return eat_line(i, line)

    def global_ProjectConfiguration_postSolution_handler(i, line):
        def func(i, line):
            return (1, (line.replace('Win32', 'x86'),))
            return (1, (line,))

        current_handler[0] = global_wrap_handler(func)
        return (1, ('\tGlobalSection(ProjectConfigurationPlatforms) = postSolution',))

    def global_end_handler(i, line):
        return (1, (
            '\tGlobalSection(SolutionProperties) = preSolution',
            '\t\tHideSolutionNode = FALSE',
            '\tEndGlobalSection',
            '\tGlobalSection(ExtensibilityGlobals) = postSolution',
            '\t\tSolutionGuid = {' + str(uuid.uuid4()).upper() + '}',
            '\tEndGlobalSection',
            line,))

    def global_handler(i, line):
        handlers = {
            '\tGlobalSection(SolutionConfiguration) = preSolution': global_SolutionConfiguration_preSolution_handler,
            '\tGlobalSection(ProjectDependencies) = postSolution': global_ProjectDependencies_postSolution_handler,
            '\tGlobalSection(ProjectConfiguration) = postSolution': global_ProjectConfiguration_postSolution_handler,
            '\tGlobalSection(ExtensibilityGlobals) = postSolution': global_remove_handler,
            '\tGlobalSection(ExtensibilityAddIns) = postSolution': global_remove_handler,
            'EndGlobal': global_end_handler,
        }
        return handlers.get(line, append_line)(i, line)

    def generate_projects():
        def generate_project_depends(p):
            deps = map(lambda x: '\t\t{project_guid} = {project_guid}'.format(**x), p['project_dependencies'])
            return (['\tProjectSection(ProjectDependencies) = postProject'] + deps + ['\tEndProjectSection']) if deps else []

        def genreate_project(p):
            return ['Project("{project_type}") = "{project_name}", "{project_path}", "{project_guid}"'.format(**p)] + generate_project_depends(p) + ['EndProject']

        return tuple(reduce(list.__add__, map(genreate_project, projs.values())))


    def generate_project_handler():
        regexpProject = re.compile(r'Project\("(?P<project_type>{[0-9A-F-]+})"\) = "(?P<project_name>[^"]+)", "(?P<project_path>[^"]+)", "(?P<project_guid>{[0-9A-F-]+})"')
        begin_project = [False]

        def func(i, line):
            match = regexpProject.match(filelines[i])
            if match:
                projDict = match.groupdict()
                projDict['project_path'] = projDict['project_path'].replace('/', '\\')
                projDict['project_dependencies'] = []
                if projDict['project_type'] == u'{8BC9CEB8-8B4A-11D0-8D11-00A0C91BC942}':
                    projs[projDict['project_guid']] = projDict

                is_begin_project = begin_project[0]
                begin_project[0] = True

                return (2, () if is_begin_project else generate_projects)

            if line == 'Global':
                current_handler[0] = global_handler

            return append_line(i, line) 

        return func

    def header_handler(i, line):
        current_handler[0] = generate_project_handler()

        return (2, ('Microsoft Visual Studio Solution File, Format Version 12.00', '# Visual Studio Version 16'))

    current_handler[0] = header_handler

    ret = []
    skip = 0
    for i in xrange(0, len(filelines)):
        if skip == 0:
            skip, lines = current_handler[0](i, filelines[i])
            ret += lines if not callable(lines) else (lines,)

        skip = skip - 1

    ret2 = []
    for i in xrange(0, len(ret)):
        ret2 += ret[i]() if callable(ret[i]) else (ret[i],)

    return ret2

    #return ['Microsoft Visual Studio Solution File, Format Version 12.00', '# Visual Studio Version 16'] + [line for line in filelines][2:]

def _cure_qmake_conf(filelines, path, out):
    handlers = (
        _handle_by_regex(r'^(QMAKE_COMPILER_DEFINES\s*\+=.*\s_MSC_VER\s*=\s*)\d+(.*)$', ('\\g<1>%d\\2' % globalInfo.MSC_VER,)),
        append_line,
    )

    return _execute_handler_alllines(filelines, handlers)

def _cure_path(path, doctor, out = None):
    _saveFile(out or path, _loadFile(path, doctor, out or path))

def _cure_projects(path):
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
                    _cure_path(fp, p)
                    break
        break

def _prepare_env():
    process = subprocess.Popen(['qmake', '-v'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    match = re.compile(r'^Using Qt version (?P<major>\d+).(?P<minor>\d+).(?P<patch>\d+) in (?P<path>.*?)([/\\]lib)?$').match(process.communicate()[0].splitlines(False)[1])
    if match:
        print match.group(0)
        for k, v in match.groupdict().iteritems():
            setattr(globalInfo, k, v)

        globalInfo.path_re = "[%s%s]%s" % (globalInfo.path[0].lower(), globalInfo.path[0].upper(), globalInfo.path[1:].replace('\\', '/').replace('/', r"[/\\]"))
    else:
        raise Exception('Can\'t detect Qt version')

    platform, msvc = os.environ["QMAKESPEC"].split('-')
    if msvc.startswith('msvc'):
        msvc = msvc[4:]

    if not (platform == 'win64' or platform == 'win32') or not msvc.isdigit():
        raise Exception('QMAKESPEC must start be win32-msvcXXXX or win64-msvcXXXX')

    msvc_vers = {
        "2008": { "platformToolset": "v90", "MSC_VER": 1500, "MSC_FULL_VER": 150021022 },
        "2010": { "platformToolset": "v100", "MSC_VER": 1600, "MSC_FULL_VER": 160030319 },
        "2012": { "platformToolset": "v110", "MSC_VER": 1700, "MSC_FULL_VER": 170050727 },
        "2013": { "platformToolset": "v120", "MSC_VER": 1800, "MSC_FULL_VER": 180021005 },
        "2015": { "platformToolset": "v140", "MSC_VER": 1900, "MSC_FULL_VER": 190023026 },
        "2017": { "platformToolset": "v141", "MSC_VER": 1910, "MSC_FULL_VER": 191025017 },
        "2019": { "platformToolset": "v142", "MSC_VER": 1920, "MSC_FULL_VER": 192027508 },
        "2022": { "platformToolset": "v143", "MSC_VER": 1930, "MSC_FULL_VER": 193030705 },

        "2012_xp": { "platformToolset": "v110_xp", "MSC_VER": 1700, "MSC_FULL_VER": 170050727 },
        "2013_xp": { "platformToolset": "v120_xp", "MSC_VER": 1800, "MSC_FULL_VER": 180021005 },
        "2015_xp": { "platformToolset": "v140_xp", "MSC_VER": 1900, "MSC_FULL_VER": 190023026 },
        "2017_xp": { "platformToolset": "v141_xp", "MSC_VER": 1910, "MSC_FULL_VER": 191025017 },
    }

    if not msvc in msvc_vers:
        raise Exception('QMAKESPEC is not found')

    for k, v in msvc_vers[msvc].iteritems():
        setattr(globalInfo, k, v)

    globalInfo.temp_mkspec = tempfile.mkdtemp()

    _cure_path(os.path.join(globalInfo.path, "mkspecs", "win32-msvc2010", "qmake.conf"), _cure_qmake_conf, os.path.join(globalInfo.temp_mkspec, "qmake.conf"))
    shutil.copyfile(os.path.join(globalInfo.path, "mkspecs", "win32-msvc2005", "qplatformdefs.h"), os.path.join(globalInfo.temp_mkspec, "qplatformdefs.h"))

    return

def _clear_env():
    if globalInfo.temp_mkspec:
        shutil.rmtree(globalInfo.temp_mkspec)

def _signal_handler(sig, frame):
    _clear_env()
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, _signal_handler)

    _prepare_env()

    command_list = ['qmake', '-tp', 'vc', '-r', '-spec', globalInfo.temp_mkspec] + sys.argv[1:]

    print u'Running qmake @ ' + os.getcwdu()
    process = subprocess.Popen(
        command_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)

    for proj in _getProjects(process.communicate()[0]):
        _cure_projects(proj)

    _clear_env()

if __name__ == '__main__':
    main()
