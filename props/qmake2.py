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

toolset = 'v90'
end_project = '</Project>'

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

def append_line(_, line):
    return (1, (line,))

def eat_line(_, line):
    return (1, ())

def _cure_vcxproj(filelines):
    base_handler = (
        _handle_by_regex(r'^(\s*)<PropertyGroup Label="Globals">$', ('\\g<0>', '\\1  <PlatformToolset>%s</PlatformToolset>' % toolset)),
        _handle_by_regex(r'^(\s*)<ConfigurationType>DynamicLibrary</ConfigurationType>$', ('\\g<0>', '\\1<GenerateManifest>false</GenerateManifest>')),
        _handle_by_regex(r'^(\s*)<(ResourceOutputFileName)>\S+\/\$\(InputName\)(.res<\/\2>)$', ('\\1<\\2>$(OutDir)$(ProjectName)\\3',)),

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

        _handle_custom_build(filelines),
        _handle_by_regex(r'^(\s*)<(\S+)(.*)>(.*)\$\(NOINHERIT\)(.*)</\2>$', ('\\1<\\2\\3>\\4\\5</\\2>',)),
        _handle_by_regex(r'^(\s*)<(\S+)(.*)>(.*)\$\(INHERIT\)(.*)</\2>$', ('\\1<\\2\\3>\\4%(\\2)\\5</\\2>',)),
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

        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\qrc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\moc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+\\.+.moc)">$'),
    ) if enabledLibs else ()

    handlers = base_handler + qt_handler + (append_line, )

    ret = []
    skip = 0
    for i in xrange(0, len(filelines)):
        if skip == 0:
            skip, lines = _execute_handler(i, filelines[i], handlers)
            ret += lines

        skip = skip - 1

    return ret

def _cure_vcxproj_filters(filelines):
    return filelines

def _cure_sln(filelines):
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

    def replace_win32_to_x86(second_handler):
        def func(i, line):
            return second_handler(i, line.replace('Win32', 'x86'))

        return func

    def global_SolutionConfiguration_preSolution_handler(i, line):
        h = _handle_by_regex(r'^(\s+)(.+) = (.+)$', ('\\1\\3 = \\3',))

        current_handler[0] = global_wrap_handler(h)

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
        current_handler[0] = global_wrap_handler(append_line)
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

