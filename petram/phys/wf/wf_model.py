'''

   WF module

   physics module which defines physics directly using MFEM weakform 
   integrators 

'''
import numpy as np

from petram.model import Domain, Bdry, Point, Pair
from petram.phys.phys_model import Phys, PhysModule

import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('WF_Model')

txt_predefined = ''    
model_basename = 'WF'

class WF_DefDomain(Domain, Phys):
    can_delete = False
    def __init__(self, **kwargs):
        super(WF_DefDomain, self).__init__(**kwargs)

    
    def get_panel1_value(self):
        return None

    def import_panel1_value(self, v):
        pass

class WF_DefBdry(Bdry, Phys):
    can_delete = False
    is_essential = False    
    def __init__(self, **kwargs):
        super(WF_DefBdry, self).__init__(**kwargs)
        Phys.__init__(self)

    def attribute_set(self, v):
        super(WF_DefBdry, self).attribute_set(v)        
        v['sel_readonly'] = False
        v['sel_index'] = ['remaining']
        return v
        
    def get_possible_bdry(self):
        return []
    
class WF_DefPoint(Point, Phys):
    can_delete = False
    is_essential = False
    def __init__(self, **kwargs):
        super(WF_DefPoint, self).__init__(**kwargs)
        Phys.__init__(self)

    def attribute_set(self, v):
        super(WF_DefPoint, self).attribute_set(v)        
        v['sel_readonly'] = False
        v['sel_index'] = ['']
        return v
        
class WF_DefPair(Pair, Phys):
    can_delete = False
    is_essential = False
    is_complex = False
    def __init__(self, **kwargs):
        super(WF_DefPair, self).__init__(**kwargs)
        Phys.__init__(self)
        
    def attribute_set(self, v):
        super(WF_DefPair, self).attribute_set(v)
        v['sel_readonly'] = False
        v['sel_index'] = []
        return v

class WF(PhysModule):
    dim_fixed = False    
    def __init__(self, **kwargs):
        super(WF, self).__init__()
        Phys.__init__(self)
        self['Domain'] = WF_DefDomain()
        self['Boundary'] = WF_DefBdry()
        self['Point'] = WF_DefPoint()        
        self['Pair'] = WF_DefPair()        
        
    @property
    def dep_vars(self):
        ret = self.dep_vars_base
        ret = [x + self.dep_vars_suffix for x in ret]        
        if self.generate_dt_fespace:
            ret = ret+ [x + "t" for x in ret]        
        return ret
    
    @property 
    def dep_vars_base(self):
        if self.vdim > 1:
            val = ["".join(self.dep_vars_base_txt.split(','))]
        else:
            val =  self.dep_vars_base_txt.split(',')
        return val
    
    @property 
    def dep_vars0(self):
        if self.vdim > 1:
            val = ["".join(self.dep_vars_base_txt.split(','))]
        else:
            val =  self.dep_vars_base_txt.split(',')
        return [x + self.dep_vars_suffix for x in val]            

    @property 
    def der_vars(self):
        names = []
        if self.vdim > 1:
            return self.dep_vars_base_txt.split(',')
        else:        
            for t in self.dep_vars:
                for x in self.ind_vars.split(","):
                    names.append(t+x.strip())
            return names

    def postprocess_after_add(self, engine):
        try:
            sdim = engine.meshes[0].SpaceDimension()
        except:
            return
        if sdim == 3:
            self.ind_vars = 'x, y, z'
        elif sdim == 2:            
            self.ind_vars = 'x, y'    
        elif sdim == 1:
            self.ind_vars = 'x'
        else:
            pass
    def is_complex(self):
        return self.is_complex_valued
    
    def get_fec(self):
        v = self.dep_vars
        return [(vv, self.element) for vv in v]
    
    def attribute_set(self, v):
        v = super(WF, self).attribute_set(v)
        v["element"] = 'H1_FECollection'
        v["dim"] = 2
        v["ind_vars"] = 'x, y'
        v["dep_vars_suffix"] = ''
        v["dep_vars_base_txt"] = 'u'
        v["is_complex_valued"] = False
        v["vdim"] = 1
        return v

    def panel1_param(self):
        import wx        
        panels = super(WF, self).panel1_param()
        panels[1] = ["element", "H1", 4,
                     {"style":wx.CB_READONLY, 
                     "choices": ["H1_FECollection",
                                 "L2_FECollection",
                                 "ND_FECollection",
                                 "RT_FECollection",
                                 "DG_FECollection"]}]

        a, b = self.get_var_suffix_var_name_panel()
        panels.extend([
                ["indpendent vars.", self.ind_vars, 0, {}],
                ["complex", self.is_complex_valued, 3, {"text":""}],
                a, b, 
                ["derived vars.", ','.join(self.der_vars), 2, {}],
                ["predefined ns vars.", txt_predefined , 2, {}],
                ["generate d/dt...", self.generate_dt_fespace, 3, {"text":' '}],])
        return panels
                      
    def get_panel1_value(self):
        names  =  self.dep_vars_base_txt
        names2  = ', '.join(self.der_vars)
        val =  super(WF, self).get_panel1_value()
                      
        val.extend([self.ind_vars, self.is_complex_valued,
                    self.dep_vars_suffix,
                     names, names2, txt_predefined,
                     self.generate_dt_fespace])
        return val
                      
    def import_panel1_value(self, v):
        import ifigure.widgets.dialog as dialog
        
        v = super(WF, self).import_panel1_value(v)
        self.ind_vars =  str(v[0])
        self.is_complex_valued = bool(v[1])
        self.dep_vars_suffix =  str(v[2])
        if len(v[3].split(',')) > 1:
            if (self.element.startswith('RT') or
                self.element.startswith('ND')):
                dialog.showtraceback(parent = None,
                                     txt="RT/ND element can not be vectorized",
                                     title="Error",
                                     traceback="No vector dim for RT/ND")
                self.element = "H1_FECollection"
        self.dep_vars_base_txt = ','.join([x.strip() for x in str(v[3]).split(',')])
        print v[3], str(v[3]).split(',')
        if self.element.startswith("H1") or self.element.startswith("L2"):
            self.vdim = len(str(v[3]).split(','))
        else:
            self.vdim = 1
        self.generate_dt_fespace = bool(v[6])

    def get_possible_domain(self):
        from wf_constraints import WF_WeakDomainBilinConstraint, WF_WeakDomainLinConstraint
        return [WF_WeakDomainBilinConstraint, WF_WeakDomainLinConstraint]
    
    def get_possible_bdry(self):
        from wf_constraints import WF_WeakBdryBilinConstraint, WF_WeakBdryLinConstraint
        from wf_essential import WF_Essential
        return [WF_Essential, WF_WeakBdryBilinConstraint, WF_WeakBdryLinConstraint]
    
    def get_possible_point(self):
        from wf_constraints import WF_WeakPointBilinConstraint, WF_WeakPointLinConstraint
        #from wf_essential import WF_Essential
        return [WF_WeakPointBilinConstraint, WF_WeakPointLinConstraint]
    
    def get_possible_pair(self):
        from wf_pairs import WF_PeriodicBdr
        #periodic bc
        return [WF_PeriodicBdr]
    
    def add_variables(self, v, name, solr, soli = None):
        from petram.helper.variables import add_coordinates
        from petram.helper.variables import add_scalar
        from petram.helper.variables import add_components
        from petram.helper.variables import add_expression
        from petram.helper.variables import add_surf_normals
        from petram.helper.variables import add_constant
        from petram.helper.variables import GFScalarVariable        

        ind_vars = [x.strip() for x in self.ind_vars.split(',')]
        suffix = self.dep_vars_suffix

        #from petram.helper.variables import TestVariable
        #v['debug_test'] =  TestVariable()
        
        add_coordinates(v, ind_vars)        
        add_surf_normals(v, ind_vars)

        dep_vars = self.dep_vars
        isVectorFE = (self.element.startswith("ND") or self.element.startswith("RT"))

        for dep_var in dep_vars:
            if name != dep_var: continue
            if isVectorFE:
                    add_components(v, dep_var, "", ind_vars, solr, soli)
            else:
                if self.vdim == 1:
                    add_scalar(v, dep_var, "", ind_vars, solr, soli)
                else:
                    names = self.dep_vars_base_txt.split(',')
                    for k, n in enumerate(names):
                        v[n] = GFScalarVariable(solr, soli, comp=k+1)
        return v
