"""Validate and merge JVM arguments without a shell or UI dependency."""
import re
import shlex


def parse_jvm(text):
    lexer = shlex.shlex(str(text or ''), posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    lexer.escape = ''  # Preserve Windows paths, allow quoted properties with spaces.
    args = list(lexer)
    for arg in args:
        if not arg.startswith(('-D', '-XX:', '-X', '-ea', '-da', '-esa', '-dsa', '-verbose')) or '\x00' in arg:
            raise ValueError('这里只填写 JVM 参数，例如 -XX:+UseG1GC；不填写 Java 路径、主类或游戏参数。')
        if arg.startswith(('-Xmx', '-Xms')):
            raise ValueError('内存大小请使用内存分配选项，避免与启动器预算冲突。')
    return args


def apply_jvm(command, text):
    custom = parse_jvm(text)
    command = list(command)
    if any(re.fullmatch(r'-XX:\+Use\w+GC', arg) for arg in custom):
        command = [arg for arg in command if arg != '-XX:+UseG1GC']
    return command[:1] + custom + command[1:]
