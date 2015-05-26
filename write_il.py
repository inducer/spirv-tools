import re
import sys

import spirv

def output_instruction(stream, module, instr, is_raw_mode, indent='  '):
    """Output one instruction."""
    line = indent
    if instr.result_id is not None:
        line = line + instr.result_id + ' = '
    line = line + instr.name
    if instr.type is not None:
        line = line + ' ' + module.type_id_to_name[instr.type]

    if not is_raw_mode:
        line = line + format_decorations_for_instr(module, instr)

    if instr.operands:
        line = line + ' '
        for operand in instr.operands:
            if operand in module.id_to_alias:
                operand = module.id_to_alias[operand]
            if operand in module.type_id_to_name:
                operand = module.type_id_to_name[operand]
            line = line + operand + ', '
        line = line[:-2]

    stream.write(line + '\n')


def get_decorations(module, instr_id):
    decorations = []
    for instr in module.decoration_instructions:
        if instr.name == 'OpDecorate' and instr.operands[0] == instr_id:
            decorations.append(instr)
    return decorations


def get_symbol_name(module, symbol_id):
    if symbol_id in module.id_to_alias:
        return module.id_to_alias[symbol_id]

    for instr in module.debug_instructions:
        if instr.name == 'OpName' and instr.operands[0] == symbol_id:
            name = instr.operands[1]
            name = name[1:-1]

            # glslang tend to add type information to function names.
            # E.g. "foo(vec4)" get the symbol name "foo(vf4;"
            # Truncate such names to fit our IL.
            regex = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*')
            match = regex.match(name)
            new_name = match.group(0)
            if new_name != name:
                sys.stderr.write('warning: truncated symbol name "'
                                 + name + '" to "' + new_name + '"\n')

            symbol_name = '@' + new_name
            break
    else:
        symbol_name = '@' + symbol_id[1:]

    module.id_to_alias[symbol_id] = symbol_name
    module.alias_to_id[symbol_name] = symbol_id

    return symbol_name


def format_decoration(decoration_instr):
    res = decoration_instr.operands[1]
    if decoration_instr.operands[2:]:
        res = res + '('
        for param in decoration_instr.operands[2:]:
            res = res + param + ', '
        res = res[:-2] + ')'
    return res


def format_decorations_for_instr(module, instr):
    line = ''
    decorations = get_decorations(module, instr.result_id)
    for decoration in decorations:
        line = line + ' ' + format_decoration(decoration)
    return line


def output_global_variable(stream, module, instr):
    """Output one global variable."""
    assert instr.name == 'OpVariable'
    ptr_instr = module.id_to_instruction[instr.type]
    assert ptr_instr.operands[0] == instr.operands[0]  # Verify storage class
    variable_type = module.type_id_to_name[ptr_instr.operands[1]]
    symbol_name = get_symbol_name(module, instr.result_id)
    line = symbol_name + ' = ' + instr.operands[0] + ' ' + variable_type

    line = line + format_decorations_for_instr(module, instr)

    stream.write(line + '\n')


def output_global_instructions_raw(stream, module):
    """Output all instructions up to the first function (raw mode)."""

    output_order = ['OpSource',
                    'OpSourceExtension',
                    'OpCompileFlag',
                    'OpExtension',
                    'OpMemoryModel',
                    'OpEntryPoint',
                    'OpExecutionMode']

    for target in output_order:
        for instr in module.initial_instructions:
            if instr.name == target:
                output_instruction(stream, module, instr, True, indent='')

    if module.initial_instructions:
        stream.write('\n')
        for instr in module.initial_instructions:
            if instr.name not in output_order:
                output_instruction(stream, module, instr, True, indent='')

    if module.debug_instructions:
        stream.write('\n')
        for instr in module.debug_instructions:
            output_instruction(stream, module, instr, True, indent='')

    if module.decoration_instructions:
        stream.write('\n')
        for instr in module.decoration_instructions:
            output_instruction(stream, module, instr, True, indent='')

    if module.type_declaration_instructions:
        stream.write('\n')
        for instr in module.type_declaration_instructions:
            output_instruction(stream, module, instr, True, indent='')

    if module.constant_instructions:
        stream.write('\n')
        for instr in module.constant_instructions:
            output_instruction(stream, module, instr, True, indent='')

    if module.global_variable_instructions:
        stream.write('\n')
        for instr in module.global_variable_instructions:
            output_instruction(stream, module, instr, True, indent='')


def add_type_if_needed(module, instr, needed_types):
    if instr.name in spirv.TYPE_DECLARATION_INSTRUCTIONS:
        if instr.name != 'OpTypeFunction':
            if module.type_id_to_name[instr.result_id] == instr.result_id:
                needed_types.add(instr.result_id)
        for operand in instr.operands:
            if operand[0] == '%':
                type_instr = module.id_to_instruction[operand]
                add_type_if_needed(module, type_instr, needed_types)
    if instr.type is not None:
        if module.type_id_to_name[instr.type] == instr.type:
            needed_types.add(instr.type)


def get_needed_types(module):
    needed_types = set()
    for function in module.functions:
        for basic_block in function.basic_blocks:
            for instr in basic_block.instrs:
                add_type_if_needed(module, instr, needed_types)
        for arg in function.arguments:
            add_type_if_needed(module, module.id_to_instruction[arg], needed_types)
    for instr in module.instructions:
        if instr.name == 'OpVariable':
            type_instr = module.id_to_instruction[instr.type]
            assert type_instr.name == 'OpTypePointer'
            ptr_type_instr = module.id_to_instruction[type_instr.operands[1]]
            add_type_if_needed(module, ptr_type_instr, needed_types)
        elif instr.name not in spirv.TYPE_DECLARATION_INSTRUCTIONS:
            add_type_if_needed(module, instr, needed_types)
    return needed_types


def output_global_instructions(stream, module):
    """Output all instructions up to the first function."""
    output_order = ['OpSource',
                    'OpSourceExtension',
                    'OpCompileFlag',
                    'OpExtension',
                    'OpMemoryModel',
                    'OpEntryPoint',
                    'OpExecutionMode']

    for target in output_order:
        for instr in module.initial_instructions:
            if instr.name == target:
                output_instruction(stream, module, instr, False, indent='')

    if module.initial_instructions:
        stream.write('\n')
        for instr in module.initial_instructions:
            if instr.name not in output_order:
                output_instruction(stream, module, instr, False, indent='')

    if module.type_declaration_instructions:
        stream.write('\n')
        needed_types = get_needed_types(module)
        for instr in module.type_declaration_instructions:
            if instr.result_id in needed_types:
                output_instruction(stream, module, instr, False, indent='')

    if module.constant_instructions:
        stream.write('\n')
        for instr in module.constant_instructions:
            output_instruction(stream, module, instr, False, indent='')

    if module.global_variable_instructions:
        stream.write('\n')
        for instr in module.global_variable_instructions:
            output_global_variable(stream, module, instr)


def output_basic_block(stream, module, basic_block, is_raw_mode):
    """Output one basic block."""
    if is_raw_mode:
        stream.write(basic_block.name + ' = OpLabel\n')
    else:
        stream.write(basic_block.name + ':\n')

    for instr in basic_block.instrs:
        output_instruction(stream, module, instr, is_raw_mode)


def output_function_raw(stream, module, func):
    """Output one function (raw mode)."""
    stream.write('\n')
    stream.write(func.name + ' = OpFunction ' + func.return_type + ' '
                 + func.function_control + ', ' + func.function_type_id + '\n')
    for arg in func.arguments:
        instr = module.id_to_instruction[arg]
        output_instruction(stream, module, instr, True, '')

    for basic_block in func.basic_blocks:
        output_basic_block(stream, module, basic_block, True)

    stream.write('OpFunctionEnd\n')


def output_function(stream, module, func):
    """Output one function (pretty-printed mode)."""
    stream.write('\n')
    symbol_name = get_symbol_name(module, func.name)
    line = "define " + module.type_id_to_name[func.return_type] + " "
    line = line + symbol_name + "("
    if func.argument_types:
        for arg_name, arg_type in zip(func.arguments, func.argument_types):
            line = line + module.type_id_to_name[arg_type]
            line = line + " " + arg_name + ", "
        line = line[:-2]
    line = line + ") {\n"
    stream.write(line)

    for basic_block in func.basic_blocks:
        if basic_block != func.basic_blocks[0]:
            stream.write('\n')
        output_basic_block(stream, module, basic_block, False)

    stream.write('}\n')


def output_functions(stream, module, is_raw_mode):
    """Output all functions."""
    for func in module.functions:
        if is_raw_mode:
            output_function_raw(stream, module, func)
        else:
            output_function(stream, module, func)


def generate_function_symbols(module):
    """Add all function names to the symbol table."""
    for func in module.functions:
        get_symbol_name(module, func.name)


def write_module(stream, module, is_raw_mode):
    if is_raw_mode:
        output_global_instructions_raw(stream, module)
    else:
        generate_function_symbols(module)
        output_global_instructions(stream, module)
    output_functions(stream, module, is_raw_mode)
