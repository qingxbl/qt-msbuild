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

def _handle_remove_range_with_detail(filelines, exp):
    compiled = re.compile(exp);

    def func(i, line):
        match = compiled.match(line)
        if not match:
            return 0, match

        stop = filelines.index('%(indent)s</%(mark)s>' % match.groupdict(), i)
        return stop - i + 1, match
    return func

def _handle_remove_range(filelines, exp):
    with_detail = _handle_remove_range_with_detail(filelines, exp)

    def func(i, line):
        return with_detail(i, line)[0]
    return func

def _moc_fix_header(ret, filelines):
    rangeChecker = _handle_remove_range_with_detail(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+)">$')
    mocCustomBuildForMoc = re.compile(r'^(\s+)<AdditionalInputs Condition=".+">.*\moc\.exe;.*</AdditionalInputs>$')

    def finish():
        ret.append(r'''  <PropertyGroup>''')
        ret.append(r'''    <BeforeClCompileTargets>''')
        ret.append(r'''      $(BeforeClCompileTargets);''')
        ret.append(r'''      _QtMoc;''')
        ret.append(r'''    </BeforeClCompileTargets>''')
        ret.append(r'''    <CppCleanDependsOn>''')
        ret.append(r'''      $(CppCleanDependsOn);''')
        ret.append(r'''      CleanupQtMoc;''')
        ret.append(r'''    </CppCleanDependsOn>''')
        ret.append(r'''  </PropertyGroup>''')
        ret.append(r'''  <Target Name="_QtMoc" DependsOnTargets="_QtMocBaseTask;_QtMocTask" />''')
        ret.append(r'''  <Target Name="_QtMocBaseTask" Condition="'@(ClInclude)' != ''">''')
        ret.append(r'''    <ItemGroup>''')
        ret.append(r'''      <QtMocFiles Include="@(ClInclude)" Condition="'%(ClInclude.Command)' != ''" />''')
        ret.append(r'''    </ItemGroup>''')
        ret.append(r'''  </Target>''')
        ret.append(r'''  <Target Name="_QtMocTask" Condition="'@(QtMocFiles)' != ''" Inputs="@(QtMocFiles)" Outputs="%(QtMocFiles.Outputs)">''')
        ret.append(r'''    <Message Importance="high" Text="%(QtMocFiles.Message)" />''')
        ret.append(r'''    <Exec Command="%(QtMocFiles.Command)" Outputs="%(QtMocFiles.Outputs)" />''')
        ret.append(r'''  </Target>''')
        ret.append(r'''  <Target Name="CleanupQtMoc" DependsOnTargets="_QtMocBaseTask">''')
        ret.append(r'''    <Delete Files="%(QtMocFiles.Outputs)" />''')
        ret.append(r'''  </Target>''')

    def func(i, line):
        if line == end_project:
            #finish()
            return 0

        skip, match = rangeChecker(i, line)
        if skip == 0 or not mocCustomBuildForMoc.match(filelines[i + 1]):
            return 0

        ret.append('%(indent)s<ClInclude Include="%(file)s" />' % match.groupdict())
        return skip
    return func

def _moc_all_in_one(ret, filelines):
    mocRe = re.compile(r'^(?P<indent>\s*)<ClCompile Include="(?P<configuration>debug|release)\\(?P<file>moc_.*\.cpp)">')
    mocs = {}

    def moc_all(kv):
        configuration = kv[0]
        cond = 'Condition="&apos;$(Configuration.toLower())&apos;==&apos;' + configuration + '&apos;"'
        ret.append('  <PropertyGroup ' + cond + '>')
        ret.append('    <QtMocSingleFileName>' + configuration + '\\mocall_$(ProjectName)$(DefaultLanguageSourceExtension)</QtMocSingleFileName>')
        ret.append('  </PropertyGroup>')
        ret.append('  <ItemGroup ' + cond + '>')
        ret.extend(map(lambda v: '    <QtMocCpp Include="' + configuration + '\\' + v + '" />', kv[1]))
        ret.append('  </ItemGroup>')

    def finish():
        if len(mocs) != 0:
            ret.append('  <PropertyGroup>')
            ret.append('    <BeforeClCompileTargets>')
            ret.append('      $(BeforeClCompileTargets);')
            ret.append('      _QtMocTaskHeaderSingleFileMode;')
            ret.append('    </BeforeClCompileTargets>')
            ret.append('    <CppCleanDependsOn>')
            ret.append('      $(CppCleanDependsOn);')
            ret.append('      CleanupQtMocTaskHeaderSingleFileMode;')
            ret.append('    </CppCleanDependsOn>')
            ret.append('  </PropertyGroup>')

            map(lambda kv: moc_all(kv), mocs.iteritems())

            ret.append(r'''  <Target Name="_QtMocTaskHeaderSingleFileMode" Condition="'@(QtMocCpp)' != ''" Inputs="@(QtMocCpp)" Outputs="$(QtMocSingleFileName)">''')
            ret.append(r'''    <Message Importance="high" Text="MOCAll $(QtMocSingleFileName)" />''')
            ret.append(r'''    <ItemGroup>''')
            ret.append(r'''      <QtMocHeaderSingleFileContent Include="#include &quot;$([MSBuild]::MakeRelative($([System.IO.Path]::GetDirectoryName($([System.IO.Path]::GetFullPath('$(QtMocSingleFileName)')))), $([System.IO.Path]::GetFullPath('%(QtMocCpp.Identity)'))))&quot;" />''')
            ret.append(r'''    </ItemGroup>''')
            ret.append(r'''    <WriteLinesToFile File="$(QtMocSingleFileName)" Lines="@(QtMocHeaderSingleFileContent)" Overwrite="true" />''')
            ret.append(r'''    <ItemGroup>''')
            ret.append(r'''      <QtMocHeaderSingleFileContent Remove="@(QtMocHeaderSingleFileContent)" />''')
            ret.append(r'''    </ItemGroup>''')
            ret.append(r'''  </Target>''')
            ret.append(r'''  <Target Name="CleanupQtMocTaskHeaderSingleFileMode" Condition="'@(QtMocCpp)' != ''">''')
            ret.append(r'''    <Delete Files="$(QtMocSingleFileName)" />''')
            ret.append(r'''  </Target>''')

    def func(i, line):
        if line == end_project:
            finish()
            return 0

        match = mocRe.match(line)
        if not match:
            return 0

        fields = match.groupdict()
        configuration = fields['configuration']
        if not mocs.has_key(configuration):
            mocs.setdefault(configuration, [])
            ret.append('%(indent)s<ClCompile Include="%(configuration)s\\mocall_$(ProjectName)$(DefaultLanguageSourceExtension)">' % fields)
            ret.append(filelines[i + 1])
            ret.append('%(indent)s</ClCompile>' % fields)

        ret.append(line)
        ret.append('%(indent)s  <ExcludedFromBuild>true</ExcludedFromBuild>' % fields)
        mocs[configuration].append(fields['file'])
        return 2

    return func

def _handle_by_regex(ret, exp, targets):
    compiled = re.compile(exp)
    def func(_, line):
        if compiled.match(line):
            for t in targets:
                ret.append(compiled.sub(t, line))
            return 1
        return 0

    return func

def _is_qt_enabled(filelines):
    compiled = re.compile(r'^\s*<PreprocessorDefinitions>.*;QT_DLL;.*</PreprocessorDefinitions>$')
    return any(compiled.match(l) for l in filelines)

def _cure_vcxproj(filelines):
    ret = []
    skip = 0

    def append_line(_, line):
        ret.append(line)
        return 1

    base_handler = (
        _handle_by_regex(ret, r'^(\s*)<PropertyGroup Label="Globals">$', ('\\g<0>', '\\1  <PlatformToolset>%s</PlatformToolset>' % toolset)),
        _handle_by_regex(ret, r'^(\s*)<ConfigurationType>DynamicLibrary</ConfigurationType>$', ('\\g<0>', '\\1<GenerateManifest>false</GenerateManifest>')),
        _handle_by_regex(ret, r'^(\s*)<(ResourceOutputFileName)>\S+\/\$\(InputName\)(.res<\/\2>)$', ('\\1<\\2>$(OutDir)%(Filename)\\3',)),

        _handle_by_regex(ret, r'^(\s*)<PlatformToolset>.*</PlatformToolset>$', ()),
        _handle_by_regex(ret, r'^(\s*)<GenerateManifest>.*</GenerateManifest>$', ()),
    )

    qt_handler = (
        _handle_by_regex(ret, r'^(\s*)<ImportGroup Label="ExtensionSettings" />$', ('\\1<ImportGroup Label="ExtensionSettings">', '\\1  <Import Project="$(SolutionDir)qt4.props" />', '\\1</ImportGroup>')),
        _handle_by_regex(ret, r'^(\s*)<ImportGroup Label="ExtensionTargets" />$', ('\\1<ImportGroup Label="ExtensionTargets">', '\\1  <Import Project="$(SolutionDir)qt4.targets" />', '\\1</ImportGroup>')),

        _moc_fix_header(ret, filelines),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>ClCompile) Include="(?P<file>.+\\moc_.+.cpp)">$'),
        _handle_remove_range(filelines, r'^(?P<indent>\s+)<(?P<mark>CustomBuild) Include="(?P<file>.+\\.+.moc)">$'),
        #_moc_all_in_one(ret, filelines),
    ) if _is_qt_enabled(filelines) else ()

    handlers = base_handler + qt_handler + (append_line, )

    for i in xrange(0, len(filelines)):
        line = filelines[i]
        if skip == 0:
            for h in handlers:
                skip = h(i, line)
                if skip != 0:
                    break

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

def main():
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

