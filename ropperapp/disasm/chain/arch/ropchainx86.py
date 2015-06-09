# coding=utf-8
#
# Copyright 2014 Sascha Schirra
#
# This file is part of Ropper.
#
# Ropper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ropper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from ropperapp.disasm.gadget import Category
from ropperapp.common.error import *
from ropperapp.common.utils import *
from ropperapp.disasm.rop import Ropper
from ropperapp.disasm.arch import x86
from ropperapp.disasm.chain.ropchain import *
from re import match
import itertools
import math

class RopChainX86(RopChain):

    MAX_QUALI = 7

    def _printHeader(self):
        toReturn = ''
        toReturn += ('#!/usr/bin/env python\n')
        toReturn += ('# Generated by ropper ropchain generator #\n')
        toReturn += ('from struct import pack\n')
        toReturn += ('\n')
        toReturn += ('p = lambda x : pack(\'I\', x)\n')

        toReturn += ('\n')

        return toReturn

    def _printRebase(self):
        toReturn = ''
        print self._usedBinaries
        for binary,section in self._usedBinaries:
            imageBase = binary.manualImagebase + section.offset if binary.manualImagebase != None else section.virtualAddress
            toReturn += ('IMAGE_BASE_%d = %s # %s\n' % (self._usedBinaries.index((binary, section)),toHex(imageBase , 4), binary.fileName))
            toReturn += ('rebase_%d = lambda x : p(x + IMAGE_BASE_%d)\n\n'% (self._usedBinaries.index((binary, section)),self._usedBinaries.index((binary, section))))
        return toReturn

    @classmethod
    def name(cls):
        return ''

    @classmethod
    def availableGenerators(cls):
        return [RopChainX86System, RopChainX86Mprotect, RopChainX86VirtualProtect]

    @classmethod
    def archs(self):
        return [x86]

    def _createDependenceChain(self, gadgets):
        """
        gadgets - list with tuples

        tuple contains:
        - method to create chaingadget
        - list with arguments
        - dict with named arguments
        - list with registers which are not allowed to override in the gadget
        """
        failed = []
        cur_len = 0
        cur_chain = ''
        counter = 0

        max_perm = math.factorial(len(gadgets))
        for x in itertools.permutations(gadgets):
            counter += 1
            self._printer.puts('\r[*] Try permuation %d / %d' % (counter, max_perm))
            found = False
            for y in failed:

                if x[:len(y)] == y:
                    found = True
                    break
            if found:
                continue
            try:
                fail = [] 
                chain2 = ''
                dontModify = []
                badRegs = []
                c = 0
                for idx in range(len(x)):
                    g = x[idx]
                    if idx != 0:
                        badRegs.extend(x[idx-1][3])

                    dontModify.extend(g[3])
                    fail.append(g)
                    chain2 += g[0](*g[1], badRegs=badRegs, dontModify=dontModify,**g[2])[0]
                

                cur_chain += chain2
                break

            except RopChainError as e:
                pass
            if len(fail) > cur_len:
                cur_len = len(fail)
                cur_chain = '# Filled registers: '
                for fa in fail[:-1]:

                    cur_chain += (fa[2]['reg']) + ', '
                cur_chain += '\n'
                cur_chain += chain2
                
            failed.append(tuple(fail))
        else:
            self._printer.printInfo('Cannot create chain which fills all registers')
        #    print('Impossible to create complete chain')
        self._printer.println('')    
        return cur_chain

    def _isModifiedOrDereferencedAccess(self, gadget, dontModify):
        
        regs = []
        for line in gadget.lines[1:]:
            line = line[1]
            if '[' in line:
                return True
            if dontModify:
                m = match('[a-z]+ (e?[abcds][ixlh]),?.*', line)
                if m and m.group(1) in dontModify:
                    return True

        return False



    def _paddingNeededFor(self, gadget):
        regs = []
        for idx in range(1,len(gadget.lines)):
            line = gadget.lines[idx][1]
            matched = match('^pop (...)$', line)
            if matched:
                regs.append(matched.group(1))
        return regs


    def _printRopInstruction(self, gadget, padding=True):
        toReturn = ('rop += rebase_%d(%s) # %s\n' % (self._usedBinaries.index((gadget._binary, gadget._section)),toHex(gadget.lines[0][0],4), gadget.simpleInstructionString()))
        if padding:
            regs = self._paddingNeededFor(gadget)
            for i in range(len(regs)):
                toReturn +=self._printPaddingInstruction()
        return toReturn

    def _printAddString(self, string):
        return ('rop += \'%s\'\n' % string)

    def _printRebasedAddress(self, addr, comment='', idx=0):
        return ('rop += rebase_%d(%s)\n' % (idx,addr))

    def _printPaddingInstruction(self, addr='0xdeadbeef'):
        return ('rop += p(%s)\n' % addr)

    def _containsZeroByte(self, addr):
        return addr & 0xff == 0 or addr & 0xff00 == 0 or addr & 0xff0000 == 0 or addr & 0xff000000 == 0

    def _createZeroByteFillerForSub(self, number):
        start = 0x01010101
        for i in xrange(start, 0x02020202):
            if not self._containsZeroByte(i) and not self._containsZeroByte(i+number):
                return i

    def _createZeroByteFillerForAdd(self, number):
        start = 0x01010101
        for i in xrange(start, 0x02020202):
            if not self._containsZeroByte(i) and not self._containsZeroByte(number-i):
                return i

    def _find(self, category, reg=None, srcdst='dst', badDst=[], badSrc=None, dontModify=None, srcEqDst=False, switchRegs=False ):
        quali = 1
        while quali < RopChainX86System.MAX_QUALI:
            for binary in self._binaries:
                for section, gadgets in binary.gadgets.items():
                    for gadget in gadgets:
                        if gadget.category[0] == category and gadget.category[1] == quali:
                            if badSrc and gadget.category[2]['src'] in badSrc:
                                continue
                            if badDst and gadget.category[2]['dst'] in badDst:
                                continue
                            if not gadget.lines[len(gadget.lines)-1][1].strip().endswith('ret') or 'esp' in gadget.simpleString():
                                continue
                            if srcEqDst and (not (gadget.category[2]['dst'] == gadget.category[2]['src'])):
                                continue
                            elif not srcEqDst and 'src' in gadget.category[2] and (gadget.category[2]['dst'] == gadget.category[2]['src']):
                                continue
                            if self._isModifiedOrDereferencedAccess(gadget, dontModify):
                                continue
                            if reg:
                                if gadget.category[2][srcdst] == reg:
                                    if (gadget._binary, gadget._section) not in self._usedBinaries:
                                        self._usedBinaries.append((gadget._binary, gadget._section))
                                    return gadget
                                elif switchRegs:
                                    other = 'src' if srcdst == 'dst' else 'dst'
                                    if gadget.category[2][other] == reg:
                                        if (gadget._binary, gadget._section) not in self._usedBinaries:
                                            self._usedBinaries.append((gadget._binary, gadget._section))
                                        return gadget
                            else:
                                if (gadget._binary, gadget._section) not in self._usedBinaries:
                                    self._usedBinaries.append((gadget._binary, gadget._section))
                                return gadget

            quali += 1


    def _createWriteStringWhere(self, what, where, reg=None, dontModify=[], idx=0):
        badRegs = []
        badDst = []
        while True:
            popReg = self._find(Category.LOAD_REG, reg=reg, badDst=badRegs, dontModify=dontModify)
            if not popReg:
                raise RopChainError('Cannot build writewhatwhere gadget!')
            write4 = self._find(Category.WRITE_MEM, reg=popReg.category[2]['dst'],  badDst=
            badDst, srcdst='src')
            if not write4:
                badRegs.append(popReg.category[2]['dst'])
                continue
            else:
                popReg2 = self._find(Category.LOAD_REG, reg=write4.category[2]['dst'], dontModify=[popReg.category[2]['dst']]+dontModify)
                if not popReg2:
                    badDst.append(write4.category[2]['dst'])
                    continue
                else:
                    break;

        if len(what) % 4 > 0:
            what += ' ' * (4 - len(what) % 4)
        toReturn = ''
        for index in range(0,len(what),4):
            part = what[index:index+4]

            toReturn += self._printRopInstruction(popReg,False)
            toReturn += self._printAddString(part)
            regs = self._paddingNeededFor(popReg)
            for i in range(len(regs)):
                toReturn +=self._printPaddingInstruction()
            toReturn += self._printRopInstruction(popReg2, False)

            toReturn += self._printRebasedAddress(toHex(where+index,4), idx=idx)
            regs = self._paddingNeededFor(popReg2)
            for i in range(len(regs)):
                toReturn +=self._printPaddingInstruction()
            toReturn += self._printRopInstruction(write4)

        return (toReturn,popReg.category[2]['dst'], popReg2.category[2]['dst'])


    def _createWriteRegValueWhere(self, what, where, dontModify=[], idx=0):
        badRegs = []
        badDst = []
        while True:


            write4 = self._find(Category.WRITE_MEM, reg=what,  badDst=badDst, dontModify=dontModify, srcdst='src')
            if not write4:
                raise RopChainError('Cannot build writewhatwhere gadget!')
            else:
                popReg2 = self._find(Category.LOAD_REG, reg=write4.category[2]['dst'], dontModify=[what]+dontModify)
                if not popReg2:
                    badDst.append(write4.category[2]['dst'])
                    continue
                else:
                    break;

        toReturn = self._printRopInstruction(popReg2, False)
        toReturn += self._printRebasedAddress(toHex(where,4), idx=idx)
        regs = self._paddingNeededFor(popReg2)
        for i in range(len(regs)):
            toReturn +=self._printPaddingInstruction()
        toReturn += self._printRopInstruction(write4)

        return (toReturn,what, popReg2.category[2]['dst'])

    def _createLoadRegValueFrom(self, what, from_reg, dontModify=[], idx=0):
        try:
            return self._createLoadRegValueFromMov(what, from_reg, dontModify, idx)
        except:
            return self._createLoadRegValueFromXchg(what, from_reg, dontModify, idx)

    def _createLoadRegValueFromMov(self, what, from_reg, dontModify=[], idx=0):
        badRegs = []
        badDst = []
        while True:


            load4 = self._find(Category.LOAD_MEM, reg=what,  badDst=badDst, dontModify=dontModify, srcdst='dst')
            if not load4:
                raise RopChainError('Cannot build loadwhere gadget!')
            else:
                popReg2 = self._find(Category.LOAD_REG, reg=load4.category[2]['src'], dontModify=[what,load4.category[2]['src']]+dontModify)
                if not popReg2:
                    badDst.append(load4.category[2]['src'])
                    continue
                else:
                    break;

        toReturn = self._printRopInstruction(popReg2, False)
        toReturn += self._printRebasedAddress(toHex(from_re,4), idx=idx)
        regs = self._paddingNeededFor(popReg2)
        for i in range(len(regs)):
            toReturn +=self._printPaddingInstruction()
        toReturn += self._printRopInstruction(load4)

        return (toReturn,what, popReg2.category[2]['dst'])

    def _createLoadRegValueFromXchg(self, what, from_reg, dontModify=[], idx=0):
        badRegs = []
        badDst = []
        while True:


            load4 = self._find(Category.XCHG_REG, reg=what,  badDst=badDst, dontModify=dontModify, srcdst='src')
            if not load4:
                raise RopChainError('Cannot build loadwhere gadget!')
            else:
                mov = self._find(Category.LOAD_MEM, reg=load4.category[2]['dst'],  badDst=badDst, dontModify=[load4.category[2]['dst']]+dontModify, srcdst='dst')
                if not mov:
                    badDst.append(load4.category[2]['dst'])
                    continue

                popReg2 = self._find(Category.LOAD_REG, reg=mov.category[2]['src'], dontModify=[what,load4.category[2]['src']]+dontModify)
                if not popReg2:
                    badDst.append(load4.category[2]['src'])
                    continue
                else:
                    break;
            
            

        toReturn = self._printRopInstruction(popReg2, False)
        toReturn += self._printRebasedAddress(toHex(from_reg,4), idx=idx)
        regs = self._paddingNeededFor(popReg2)
        for i in range(len(regs)):
            toReturn +=self._printPaddingInstruction()

        toReturn += self._printRopInstruction(mov)

        toReturn += self._printRopInstruction(load4)

        return (toReturn,what, popReg2.category[2]['dst'])

    def _createNumberSubtract(self, number, reg=None, badRegs=None, dontModify=None):
        if not badRegs:
            badRegs=[]
        while True:
            sub = self._find(Category.SUB_REG, reg=reg, badDst=badRegs, badSrc=badRegs, dontModify=dontModify)
            if not sub:
                raise RopChainError('Cannot build number with subtract gadget for reg %s!' % reg)
            popSrc = self._find(Category.LOAD_REG, reg=sub.category[2]['src'], dontModify=dontModify)
            if not popSrc:
                badRegs.append=[sub.category[2]['src']]
                continue
            popDst = self._find(Category.LOAD_REG, reg=sub.category[2]['dst'], dontModify=[sub.category[2]['src']]+dontModify)
            if not popDst:
                badRegs.append=[sub.category[2]['dst']]
                continue
            else:
                break;

        filler = self._createZeroByteFillerForSub(number)

        toReturn = self._printRopInstruction(popSrc, False)
        toReturn += self._printPaddingInstruction(toHex(filler,4))
        regs = self._paddingNeededFor(popSrc)
        for i in range(len(regs)):
            toReturn += self._printPaddingInstruction()
        toReturn += self._printRopInstruction(popDst, False)
        toReturn += self._printPaddingInstruction(toHex(filler+number,4))
        regs = self._paddingNeededFor(popDst)
        for i in range(len(regs)):
            toReturn += self._printPaddingInstruction()
        toReturn += self._printRopInstruction(sub)       
        return (toReturn, popDst.category[2]['dst'],popSrc.category[2]['dst'])

    def _createNumberAddition(self, number, reg=None, badRegs=None, dontModify=None):
        if not badRegs:
            badRegs=[]
        while True:
            sub = self._find(Category.ADD_REG, reg=reg, badDst=badRegs, badSrc=badRegs, dontModify=dontModify)
            if not sub:
                raise RopChainError('Cannot build number with addition gadget for reg %s!' % reg)
            popSrc = self._find(Category.LOAD_REG, reg=sub.category[2]['src'], dontModify=dontModify)
            if not popSrc:
                badRegs.append=[sub.category[2]['src']]
                continue
            popDst = self._find(Category.LOAD_REG, reg=sub.category[2]['dst'], dontModify=[sub.category[2]['src']]+dontModify)
            if not popDst:
                badRegs.append(sub.category[2]['dst'])
                continue
            else:
                break;

        filler = self._createZeroByteFillerForAdd(number)

        toReturn = self._printRopInstruction(popSrc, False)
        toReturn += self._printPaddingInstruction(toHex(filler,4))
        regs = self._paddingNeededFor(popSrc)
        for i in range(len(regs)):
            toReturn += self._printPaddingInstruction()
        toReturn += self._printRopInstruction(popDst, False)
        toReturn += self._printPaddingInstruction(toHex(number - filler,4))
        regs = self._paddingNeededFor(popDst)
        for i in range(len(regs)):
            toReturn += self._printPaddingInstruction()
        toReturn += self._printRopInstruction(sub)

        return (toReturn, popDst.category[2]['dst'],popSrc.category[2]['dst'])

    def _createNumberPop(self, number, reg=None, badRegs=None, dontModify=None):
        while True:
            popReg = self._find(Category.LOAD_REG, reg=reg, badDst=badRegs,dontModify=dontModify)
            if not popReg:
                raise RopChainError('Cannot build number with xor gadget!')
            incReg = self._find(Category.INC_REG, reg=popReg.category[2]['dst'], dontModify=dontModify)
            if not incReg:
                if not badRegs:
                    badRegs = []
                badRegs.append(popReg.category[2]['dst'])
            else:
                break

        toReturn = self._printRopInstruction(popReg)
        toReturn += self._printPaddingInstruction(toHex(0xffffffff,4))
        for i in range(number+1):
            toReturn += self._printRopInstruction(incReg)

        return (toReturn ,popReg.category[2]['dst'],)


    def _createNumberXOR(self, number, reg=None, badRegs=None, dontModify=None):
        while True:
            clearReg = self._find(Category.CLEAR_REG, reg=reg, badDst=badRegs, badSrc=badRegs,dontModify=dontModify, srcEqDst=True)
            if not clearReg:
                raise RopChainError('Cannot build number with xor gadget!')
            if number > 0:
                incReg = self._find(Category.INC_REG, reg=clearReg.category[2]['src'], dontModify=dontModify)
                if not incReg:
                    if not badRegs:
                        badRegs = []
                    badRegs.append(clearReg.category[2]['src'])
                else:
                    break
            else:
                break

        toReturn = self._printRopInstruction(clearReg)
        for i in range(number):
            toReturn += self._printRopInstruction(incReg)

        return (toReturn, clearReg.category[2]['dst'],)

    def _createNumberXchg(self, number, reg=None, badRegs=None, dontModify=None):
        xchg = self._find(Category.XCHG_REG, reg=reg, badDst=badRegs, dontModify=dontModify)
        if not xchg:
            raise RopChainError('Cannot build number gadget with xchg!')

        other = xchg.category[2]['src'] if xchg.category[2]['dst'] else xchg.category[2]['dst']
        
        toReturn = self._createNumber(number, other, badRegs, dontModify)[0]
        
        toReturn += self._printRopInstruction(xchg)
        return (toReturn, reg, other)

    def _createNumberNeg(self, number, reg=None, badRegs=None, dontModify=None):
        if number == 0:
            raise RopChainError('Cannot build number gadget with neg if number is 0!')
        neg = self._find(Category.NEG_REG, reg=reg, badDst=badRegs, dontModify=dontModify)
        if not neg:
            raise RopChainError('Cannot build number gadget with neg!')

        pop = self._find(Category.LOAD_REG, reg=reg, badDst=badRegs, dontModify=dontModify)
        if not pop:
            raise RopChainError('Cannot build number gadget with neg!')
        
        toReturn = self._printRopInstruction(pop)
        toReturn += self._printPaddingInstruction(toHex((~number)+1)) # two's complement
        toReturn += self._printRopInstruction(neg)
        return (toReturn, reg,)

    def _createNumber(self, number, reg=None, badRegs=None, dontModify=None, xchg=True):
        try:
            if self._containsZeroByte(number):
                try:
                    return self._createNumberNeg(number, reg, badRegs,dontModify)
                except RopChainError as e:
                    
                    if number < 50:
                        try:
                            return self._createNumberXOR(number, reg, badRegs,dontModify)
                        except RopChainError:
                            try:
                                return self._createNumberPop(number, reg, badRegs,dontModify)
                            except RopChainError:
                                try:
                                    return self._createNumberSubtract(number, reg, badRegs,dontModify)
                                except RopChainError:
                                    return self._createNumberAddition(number, reg, badRegs,dontModify)

                    else :
                        try:
                            return self._createNumberSubtract(number, reg, badRegs,dontModify)
                        except RopChainError:
                            return self._createNumberAddition(number, reg, badRegs,dontModify)
            else:
                popReg =self._find(Category.LOAD_REG, reg=reg, badDst=badRegs,dontModify=dontModify)
                if not popReg:
                    raise RopChainError('Cannot build number gadget!')
                toReturn = self._printRopInstruction(popReg)
                toReturn += self._printPaddingInstruction(toHex(number,4))
                return (toReturn , popReg.category[2]['dst'])
        except:
            return self._createNumberXchg(number, reg, badRegs, dontModify)

    def _createAddress(self, address, reg=None, badRegs=None, dontModify=None):
        popReg = self._find(Category.LOAD_REG, reg=reg, badDst=badRegs,dontModify=dontModify)
        if not popReg:
            raise RopChainError('Cannot build address gadget!')

        toReturn = ''

        toReturn += self._printRopInstruction(popReg,False)
        toReturn += self._printRebasedAddress(toHex(address, 4), idx=self._usedBinaries.index((popReg._binary, popReg._section)))
        regs = self._paddingNeededFor(popReg)
        for i in range(len(regs)):
            toReturn +=self._printPaddingInstruction()

        return (toReturn,popReg.category[2]['dst'])

    def _createSyscall(self, reg=None, badRegs=None, dontModify=None):
        syscall = self._find(Category.SYSCALL, reg=None, badDst=None, dontModify=dontModify)
        if not syscall:
            raise RopChainError('Cannot build syscall gadget!')

        toReturn = ''

        toReturn += self._printRopInstruction(syscall)

        return (toReturn,)

    def _createOpcode(self, opcode):
        
        return self._printRopInstruction(self._searchOpcode(opcode))
       

    def _searchOpcode(self, opcode):
        r = Ropper(self._binaries[0])
        gadgets = []
        for section in self._binaries[0].executableSections:
            vaddr = section.virtualAddress
            gadgets.extend(
                r.searchOpcode(section.bytes, opcode.decode('hex'), section.offset, True, section=section))

        if len(gadgets) > 0:
            return gadgets[0]
        else:
            raise RopChainError('Cannot create gadget for opcode: %x' % opcode)

    def create(self):
        pass


class RopChainX86System(RopChainX86):


    @classmethod
    def name(cls):
        return 'execve'

    def _createCommand(self, what, where, reg=None, dontModify=[], idx=0):
        if len(what) % 4 > 0:
            what = '/' * (4 - len(what) % 4) + what
        return self._createWriteStringWhere(what,where, idx=idx)

    def create(self, cmd='/bin/sh'):
        if len(cmd.split(' ')) > 1:
            raise RopChainError('No argument support for execve commands')

        self._printer.printInfo('ROPchain Generator for syscall execve:\n')
        self._printer.println('\nwrite command into data section\neax 0xb\nebx address to cmd\necx address to null\nedx address to null\n')

        section = self._binaries[0].getSection('.data')
        
        length = math.ceil(float(len(cmd))/4) * 4
        chain = self._printHeader()
        chain_tmp = '\n'
        chain_tmp += self._createCommand(cmd,section.struct.sh_offset+0x1000)[0]
        badregs = []

        while True:

            ret = self._createNumber(0x0, badRegs=badregs)
            chain_tmp += ret[0]
            try:
                chain_tmp += self._createWriteRegValueWhere(ret[1], section.struct.sh_offset+0x1000+length)[0]
                break
            except BaseException as e:
                raise e
                badregs.append(ret[1])

        gadgets = []
        gadgets.append((self._createAddress, [section.struct.sh_offset+0x1000],{'reg':'ebx'},['ebx', 'bx', 'bl', 'bh']))
        gadgets.append((self._createAddress, [section.struct.sh_offset+0x1000+length],{'reg':'ecx'},['ecx', 'cx', 'cl', 'ch']))
        gadgets.append((self._createAddress, [section.struct.sh_offset+0x1000+length],{'reg':'edx'},['edx', 'dx', 'dl', 'dh']))
        gadgets.append((self._createNumber, [0xb],{'reg':'eax'},['eax', 'ax', 'al', 'ah']))

        self._printer.printInfo('Try to create chain which fills registers without delete content of previous filled registers')
        chain_tmp += self._createDependenceChain(gadgets)
        try:
            self._printer.printInfo('Look for syscall gadget')
            chain_tmp += self._createSyscall()[0]
            self._printer.printInfo('syscall gadget found')

        except RopChainError:
            try:
                self._printer.printInfo('No syscall gadget found!')
                self._printer.printInfo('Look for int 0x80 opcode')

                chain_tmp += self._createOpcode('cd80')
                self._printer.printInfo('int 0x80 opcode found')

            except:
                try:
                    self._printer.printInfo('No int 0x80 opcode found')
                    self._printer.printInfo('Look for call gs:[0x10] opcode')
                    chain_tmp += self._createOpcode('65ff1510000000')
                    self._printer.printInfo('call gs:[0x10] found')
                except RopChainError:
                    self._printer.printInfo('No call gs:[0x10] opcode found')


        chain += self._printRebase()
        chain += 'rop = \'\'\n'

        chain += chain_tmp
        chain += 'print rop'
        print(chain)


class RopChainX86Mprotect(RopChainX86):
    """
    Builds a ropchain for mprotect syscall
    eax 0x7b
    ebx address
    ecx size
    edx 0x7 -> RWE
    """

    @classmethod
    def name(cls):
        return 'mprotect'

    def _createJmp(self, reg='esp'):
        r = Ropper(self._binaries[0])
        gadgets = []
        for section in self._binaries[0].executableSections:
            vaddr = section.virtualAddress
            gadgets.extend(
                r.searchJmpReg(section.bytes, reg, vaddr, section=section))



        if len(gadgets) > 0:
            if (gadgets[0]._binary, gadgets[0]._section) not in self._usedBinaries:
                self._usedBinaries.append((gadgets[0]._binary, gadgets[0]._section))
            return self._printRopInstruction(gadgets[0])
        else:
            return None

    def __extract(self, param):
        if not match('0x[0-9a-fA-F]{1,8}:0x[0-9a-fA-F]+', param) or not match('0x[0-9a-fA-F]{1,8}:[0-9]+', param):
            raise RopChainError('Parameter have to have the following format: <hexnumber>:<hexnumber> or <hexnumber>:<number>')

        split = param.split(':')
        if isHex(split[1]):
            return (int(split[0], 16), int(split[1], 16))
        else:
            return (int(split[0], 16), int(split[1], 10))


    def create(self, param=None):
        if not param:
            raise RopChainError('Missing parameter: address:size')

        address, size = self.__extract(param)
        self._printer.printInfo('ROPchain Generator for syscall mprotect:\n')
        self._printer.println('eax 0x7b\nebx address\necx size\nedx 0x7 -> RWE\n')

        chain = self._printHeader()
        
        chain += '\n\nshellcode = \'\\xcc\'*100\n\n'

        gadgets = []
        gadgets.append((self._createNumber, [address],{'reg':'ebx'},['ebx', 'bx', 'bl', 'bh']))
        gadgets.append((self._createNumber, [size],{'reg':'ecx'},['ecx', 'cx', 'cl', 'ch']))
        gadgets.append((self._createNumber, [0x7],{'reg':'edx'},['edx', 'dx', 'dl', 'dh']))
        gadgets.append((self._createNumber, [0x7d],{'reg':'eax'},['eax', 'ax', 'al', 'ah']))

        self._printer.printInfo('Try to create chain which fills registers without delete content of previous filled registers')
        chain_tmp = ''
        chain_tmp += self._createDependenceChain(gadgets)
        try:
            self._printer.printInfo('Look for syscall gadget')
            chain_tmp += self._createSyscall()[0]
            self._printer.printInfo('syscall gadget found')
        except RopChainError:
            chain_tmp += '\n# ADD HERE SYSCALL GADGET\n\n'
            self._printer.printInfo('No syscall gadget found!')

        self._printer.printInfo('Look for jmp esp')
        jmp_esp = self._createJmp()
        if jmp_esp:
            self-_printer.printInfo('jmp esp found')
            chain_tmp += jmp_esp
        else:
            self-_printer.printInfo('no jmp esp found')
            chain_tmp += '\n# ADD HERE JMP ESP\n\n'

        chain += self._printRebase()
        chain += '\nrop = \'\'\n'
        chain += chain_tmp
        chain += 'rop += shellcode\n\n'
        chain += 'print(rop)\n'

        print(chain)

class RopChainX86VirtualProtect(RopChainX86):
    """
    Builds a ropchain for a VirtualProtect call using pushad
    eax 0x90909090
    ecx old protection (writable addr)
    edx 0x40 (RWE)
    ebx size
    esp address
    ebp return address (jmp esp)
    esi pointer to VirtualProtect
    edi ret (rop nop)
    """


    @classmethod
    def name(cls):
        return 'virtualprotect'


    def _createPushad(self):
        pushad = self._find(Category.PUSHAD)
        return self._printRopInstruction(pushad)


    def _createJmp(self, reg='esp'):
        r = Ropper(self._binaries[0])
        gadgets = []
        for section in self._binaries[0].executableSections:
            vaddr = section.offset
            gadgets.extend(
                r.searchJmpReg(section.bytes, reg, vaddr, section=section))



        if len(gadgets) > 0:
            if (gadgets[0]._binary, gadgets[0]._section) not in self._usedBinaries:
                self._usedBinaries.append((gadgets[0]._binary, gadgets[0]._section))
            return gadgets[0]
        else:
            return ''

    def __extract(self, param):
        if not match('0x[0-9a-fA-F]{1,8}:0x[0-9a-fA-F]+', param) or not match('0x[0-9a-fA-F]{1,8}:[0-9]+', param):
            raise RopChainError('Parameter have to have the following format: <hexnumber>:<hexnumber> or <hexnumber>:<number>')

        split = param.split(':')
        if isHex(split[1]):
            return (int(split[0], 16), int(split[1], 16))
        else:
            return (int(split[0], 16), int(split[1], 10))


    def create(self, param=None):
        if not param:
            raise RopChainError('Missing parameter: address:size')

        self._printer.printInfo('Ropchain Generator for VirtualProtect:\n')
        self._printer.println('eax 0x90909090\necx old protection (writable addr)\nedx 0x40 (RWE)\nebx size\nesp address\nebp return address (jmp esp)\nesi pointer to VirtualProtect\nedi ret (rop nop)\n')

        address, size = self.__extract(param)
        
        writeable_ptr = 0xffffffff
        jmp_esp = self._createJmp()
        ret_addr = self._searchOpcode('c3')

        chain = self._printHeader()
        
        chain += '\n\nshellcode = \'\\xcc\'*100\n\n'
        gadgets = []
        to_extend = []
        chain_tmp = ''
        try:
            self._printer.printInfo('Try to create gadget to fill esi with content of IAT address: %s' % address)
            chain_tmp += self._createLoadRegValueFrom('esi', address)[0]
            gadgets.append((self._createNumber, [address],{'reg':'eax'},['eax', 'ax', 'ah', 'al','esi','si']))
            to_extend = ['esi','si']
        except:
            self._printer.printInfo('Cannot create fill esi gadget!')
            self._printer.printInfo('Try to create this chain:\n')
            self._printer.println('eax Pointer to VirtualProtect\necx old protection (writable addr)\nedx 0x40 (RWE)\nebx size\nesp address\nebp return address (jmp esp)\nesi pointer to jmp [eax]\nedi ret (rop nop)\n')

            jmp_eax = self._searchOpcode('ff20') # jmp [eax]
            gadgets.append((self._createAddress, [jmp_eax.lines[0][0]],{'reg':'esi'},['esi','si']))
            gadgets.append((self._createNumber, [address],{'reg':'eax'},['eax', 'ax', 'ah', 'al']))


        
        gadgets.append((self._createNumber, [size],{'reg':'ebx'},['ebx', 'bx', 'bl', 'bh']+to_extend))
        gadgets.append((self._createAddress, [writeable_ptr],{'reg':'ecx'},['ecx', 'cx', 'cl', 'ch']+to_extend))
        gadgets.append((self._createAddress, [jmp_esp.lines[0][0]],{'reg':'ebp'},['ebp', 'bp']+to_extend))
        gadgets.append((self._createNumber, [0x40],{'reg':'edx'},['edx', 'dx', 'dh', 'dl']+to_extend))
        
        gadgets.append((self._createAddress, [ret_addr.lines[0][0]],{'reg':'edi'},['edi', 'di']+to_extend))

        self._printer.printInfo('Try to create chain which fills registers without delete content of previous filled registers')
        chain_tmp += self._createDependenceChain(gadgets)
        
        self._printer.printInfo('Look for pushad gadget')
        chain_tmp += self._createPushad()
        

        chain += self._printRebase()
        chain += 'rop = \'\'\n'
        chain += chain_tmp
        chain += 'rop += shellcode\n\n'
        chain += 'print(rop)\n'

        print(chain)

