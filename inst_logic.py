# * Copyright 2016, Data61
# *
# * This software may be distributed and modified according to the terms of
# * the BSD 2-Clause license. Note that NO WARRANTY is provided.
# * See "LICENSE_BSD2.txt" for details.
# *
# * @TAG(NICTA_BSD)

import syntax
import solver
import problem
import rep_graph
import search
import logic
import check

from syntax import mk_var

from target_objects import functions, trace, pairings, pre_pairings, printout
import target_objects

import re

reg_aliases = {'sb': 'r9', 'fp': 'r11', 'ip': 'r12',
        'sp': 'r13', 'lr': 'r14', 'pc': 'r15'}

reg_set = set (['r%d' % i for i in range (16)])

inst_split_re = re.compile('[_,]*')
crn_re = re.compile('cr[0123456789][0123456789]*')
pn_re = re.compile('p[0123456789][0123456789]*')
def split_inst_name_regs (nm):
	bits = inst_split_re.split (nm)
	fin_bits = []
	regs = []
	if len (bits) > 1 and pn_re.match (bits[1]):
		bits[1] = bits[1][1:]
	for bit in bits:
		bit2 = bit.lower ()
		bit2 = reg_aliases.get (bit, bit)
		if crn_re.match (bit2):
			assert bit2.startswith ('cr')
			bit2 = 'c' + bit2[2:]
		if bit2 in reg_set or bit2.startswith ('%'):
			regs.append (bit2)
			fin_bits.append ('argv%d' % (len (regs)))
		else:
			fin_bits.append (bit2)
	return (regs, '_'.join (fin_bits))

bin_globs = [('mem', syntax.builtinTs['Mem'])]
asm_globs = [('Mem', syntax.builtinTs['Mem'])]

def mk_fun (nm, word_args, ex_args, word_rets, ex_rets, globs):
	"""wrapper for making a syntax.Function with standard args/rets."""
	return syntax.Function (nm,
		[(nm, syntax.word32T) for nm in word_args] + ex_args + globs,
		[(nm, syntax.word32T) for nm in word_rets] + ex_rets + globs)

instruction_fun_specs = {
	'mcr' : ("impl'mcr", ["I"]),
	'mcr2' : ("impl'mcr", ["I"]),
	'mcrr' : ("impl'mcrr", ["I", "I"]),
	'mcrr2' : ("impl'mcrr", ["I", "I"]),
	'mrc': ("impl'mrc", ["O"]),
	'mrc2': ("impl'mrc", ["O"]),
	'mrrc': ("impl'mrrc", ["O", "O"]),
	'mrrc2': ("impl'mrrc", ["O", "O"]),
}

def add_impl_fun (impl_fname, regspecs):
	if impl_fname in functions:
		return
	ident_v = ("inst_ident", syntax.builtinTs['Token'])

	inps = [s for s in regspecs if s == 'I']
	inps = ['reg_val%d' % (i + 1) for (i, s) in enumerate (inps)]
	rets = [s for s in regspecs if s == 'O']
	rets = ['ret_val%d' % (i + 1) for (i, s) in enumerate (rets)]
	fun = mk_fun (impl_fname, inps, [ident_v], rets, [], bin_globs)
	inp_eqs = [((mk_var (nm, typ), 'ASM_IN'), (mk_var (nm, typ), 'C_IN'))
		for (nm, typ) in fun.inputs]
	inp_eqs += [((logic.mk_rodata (mk_var (nm, typ)), 'ASM_IN'),
		(syntax.true_term, 'C_IN')) for (nm, typ) in bin_globs]
	out_eqs = [((mk_var (nm, typ), 'ASM_OUT'), (mk_var (nm, typ), 'C_OUT'))
		for (nm, typ) in fun.outputs]
	out_eqs += [((logic.mk_rodata (mk_var (nm, typ)), 'ASM_OUT'),
		(syntax.true_term, 'C_OUT')) for (nm, typ) in bin_globs]
	pair = logic.Pairing (['ASM', 'C'],
		{'C': impl_fname, 'ASM': impl_fname},
		(inp_eqs, out_eqs))
	assert impl_fname not in pairings
	functions[impl_fname] = fun
	pairings[impl_fname] = [pair]

def mk_bin_inst_spec (fname):
	if not fname.startswith ("instruction'"):
		return
	if functions[fname].entry:
		return
	(_, ident) = fname.split ("'", 1)
	(regs, ident) = split_inst_name_regs (ident)
	base_ident = ident.split ("_")[0]
	if base_ident not in instruction_fun_specs:
		return
	(impl_fname, regspecs) = instruction_fun_specs[base_ident]
	add_impl_fun (impl_fname, regspecs)
	assert len (regspecs) == len (regs), (fname, regs, regspecs)
	inp_regs = [reg for (reg, d) in zip (regs, regspecs) if d == 'I']
	out_regs = [reg for (reg, d) in zip (regs, regspecs) if d == 'O']
	call = syntax.Node ('Call', 'Ret', (impl_fname,
		[syntax.mk_var (reg, syntax.word32T) for reg in inp_regs]
			+ [syntax.mk_token (ident)]
			+ [syntax.mk_var (nm, typ) for (nm, typ) in bin_globs],
		[(reg, syntax.word32T) for reg in out_regs] + bin_globs))
	assert not functions[fname].nodes
	functions[fname].nodes[1] = call
	functions[fname].entry = 1

def mk_asm_inst_spec (fname):
	if not fname.startswith ("asm_instruction'"):
		return
	if functions[fname].entry:
		return
	(_, ident) = fname.split ("'", 1)
        (args, ident) = split_inst_name_regs (ident)
	assert all ([arg.startswith ('%') for arg in args]), fname
	base_ident = ident.split ("_")[0]
	if base_ident not in instruction_fun_specs:
		return
	(impl_fname, regspecs) = instruction_fun_specs[base_ident]
	add_impl_fun (impl_fname, regspecs)
	(iscs, imems, _) = logic.split_scalar_pairs (functions[fname].inputs)
	(oscs, omems, _) = logic.split_scalar_pairs (functions[fname].outputs)
	call = syntax.Node ('Call', 'Ret', (impl_fname,
		iscs + [syntax.mk_token (ident)] + imems,
                [(v.name, v.typ) for v in oscs + omems]))
	assert not functions[fname].nodes
	functions[fname].nodes[1] = call
	functions[fname].entry = 1

def add_inst_specs ():
	for f in functions.keys ():
		mk_asm_inst_spec (f)
		mk_bin_inst_spec (f)


