import wx
import numpy as np
from os.path import dirname, basename, isfile, join
import warnings
import glob
import parser

import petram
from petram.model import Model, Bdry, Domain
from petram.namespace_mixin import NS_mixin
import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('Phys')

from petram.mfem_config import use_parallel
if use_parallel:
   import mfem.par as mfem
else:
   import mfem.ser as mfem

from petram.helper.variables import Variable, eval_code 
 
# not that PyCoefficient return only real number array
class PhysConstant(mfem.ConstantCoefficient):
    def __init__(self, value):
        self.value = value
        mfem.ConstantCoefficient.__init__(self, value)
        
    def __repr__(self):
        return self.__class__.__name__+"("+str(self.value)+")"
     
def try_eval(exprs, l, g):
    '''
    first evaulate as it is
    if the result is list.. return
    if not evaluate w/o knowing any Variables
    '''
    try:
       value = eval(exprs, l, g)
       if isinstance(value, list):
           return True, [value]          
       ll = [x for x in l if not isinstance(x, Variable)]
       gg = [x for x in g if not isinstance(x, Variable)]       
       value = eval(exprs, ll, gg)
       return True, [value]
    except:
       return False, exprs
   
class Coefficient_Evaluator(object):
    def __init__(self,  exprs,  ind_vars, l, g, real=True):
        ''' 
        this is complicated....
           elemental (or array) form 
            [1,a,3]  (a is namespace variable) is given as [[1, a (valued), 3]]

           single box
              1+1j   is given as '(1+1j)' (string)

           matrix
              given as string like '[0, 1, 2, 3, 4]'
              if variable is used it is become string element '['=variable', 1, 2, 3, 4]'
              if =Varialbe in matrix form, it is passed as [['Variable']]
        '''
        #print("exprs", exprs, type(exprs))
        flag, exprs = try_eval(exprs, l, g)
        #print("after try_eval", flag, exprs)
        if not flag:
            if isinstance(exprs, str):
                exprs = [exprs]
            elif isinstance(exprs, float):
                exprs = [exprs]               
            elif isinstance(exprs, long):
                exprs = [exprs]
            else:
               pass
        if isinstance(exprs, list) and isinstance(exprs[0], list):
            exprs = exprs[0]
        #print("final exprs", exprs)
        self.l = {}
        self.g = g
        for key in l.keys():
           self.g[key] = l[key]
        self.real = real
        self.variables = []

        self.co = []
        for expr in exprs:
           if isinstance(expr, str):
               st = parser.expr(expr.strip())
               code= st.compile('<string>')
               names = code.co_names
               for n in names:
                  if n in g and isinstance(g[n], Variable):
                       self.variables.append((n, g[n]))
               self.co.append(code)
           else:
               self.co.append(expr)
               
        # 'x, y, z' -> 'x', 'y', 'z'
        self.ind_vars = [x.strip() for x in ind_vars.split(',')]
        self.exprs = exprs
        
    def EvalValue(self, x):
        for k, name in enumerate(self.ind_vars):
           self.l[name] = x[k]
        for n, v in self.variables:           
           self.l[n] = v()

        val = [eval_code(co, self.g, self.l) for co in self.co]
        return np.array(val, copy=False).flatten()

class PhysCoefficient(mfem.PyCoefficient, Coefficient_Evaluator):
    def __init__(self, exprs, ind_vars, l, g, real=True, isArray = False):
       #if not isArray:
       #    exprs = [exprs]
       Coefficient_Evaluator.__init__(self, exprs, ind_vars, l, g, real=real)           
       mfem.PyCoefficient.__init__(self)

    def __repr__(self):
        return self.__class__.__name__+"(PhysCoefficeint)"
        
    def Eval(self, T, ip):
        for n, v in self.variables:
           v.set_point(T, ip, self.g, self.l)
        return super(PhysCoefficient, self).Eval(T, ip)

    def EvalValue(self, x):
        # set x, y, z to local variable so that we can use in
        # the expression.

        # note that this class could return array, since
        # a user may want to define multiple variables
        # as an array. In such case, subclass should pick
        # one element.
        val = Coefficient_Evaluator.EvalValue(self, x)
        if len(self.co) == 1 and len(val) == 1:
           return val[0]
        return val
             
class VectorPhysCoefficient(mfem.VectorPyCoefficient, Coefficient_Evaluator):
    def __init__(self, sdim, exprs, ind_vars, l, g, real=True):
        Coefficient_Evaluator.__init__(self, exprs,  ind_vars, l, g, real=real)
        mfem.VectorPyCoefficient.__init__(self, sdim)
        
    def __repr__(self):
        return self.__class__.__name__+"(VectorPhysCoefficeint)"
        
    def Eval(self, V, T, ip):
        for n, v in self.variables:
           v.set_point(T, ip, self.g, self.l)                      
        return super(VectorPhysCoefficient, self).Eval(V, T, ip)
       
    def EvalValue(self, x):
        return Coefficient_Evaluator.EvalValue(self, x)
     
class MatrixPhysCoefficient(mfem.MatrixPyCoefficient, Coefficient_Evaluator):
    def __init__(self, sdim, exprs,  ind_vars, l, g, real=True):
        self.sdim = sdim
        Coefficient_Evaluator.__init__(self, exprs, ind_vars, l, g, real=real)       
        mfem.MatrixPyCoefficient.__init__(self, sdim)
        
    def __repr__(self):
        return self.__class__.__name__+"(MatrixPhysCoefficeint)"
        
    def Eval(self, K, T, ip):
        for n, v in self.variables:
           v.set_point(T, ip, self.g, self.l)           
        return super(MatrixPhysCoefficient, self).Eval(K, T, ip)

    def EvalValue(self, x):
        val = Coefficient_Evaluator.EvalValue(self, x)
        # reshape tosquare matrix (not necessariliy = sdim x sdim)
        # if elment is just one, it formats to diagonal matrix

        s = val.size
        if s == 1:
            return np.zeros((self.sdim, self.sdim)) + val[0]
        else:
            dim = int(np.sqrt(s))
            return val.reshape(dim, dim)
       

from petram.phys.vtable import VtableElement, Vtable, Vtable_mixin

class Phys(Model, Vtable_mixin, NS_mixin):
    hide_ns_menu = True
    hide_nl_panel = False
    dep_vars_base = []
    der_vars_base = []

    has_essential = False
    is_complex = False
    is_secondary_condition = False   # if true, there should be other
                                     # condtion assigned to the same
                                     # edge/face/domain
    vt   = Vtable(tuple())         
    vt2  = Vtable(tuple())         
    vt3  = Vtable(tuple())
    nlterms = []
                                     
    def __init__(self, *args, **kwargs):
        super(Phys, self).__init__(*args, **kwargs)
        NS_mixin.__init__(self, *args, **kwargs)
        
    def attribute_set(self, v):
        v = super(Phys, self).attribute_set(v)
        self.vt.attribute_set(v)
        self.vt3.attribute_set(v)

        nl_config = dict()
        for k in self.nlterms: nl_config[k] = []
        v['nl_config'] = (False, nl_config)
        return v
        
    def get_possible_bdry(self):
        return []
    
    def get_possible_domain(self):
        return []                

    def get_possible_edge(self):
        return []                

    def get_possible_pair(self):
        return []        

    def get_possible_paint(self):
        return []

    def get_independent_variables(self):
        p = self.get_root_phys()
        ind_vars = p.ind_vars
        return [x.strip() for x in ind_vars.split(',')]
     
    def is_complex(self):
        return False

    def get_restriction_array(self, engine, idx = None):
        mesh = engine.meshes[self.get_root_phys().mesh_idx]
        intArray = mfem.intArray

        if isinstance(self, Domain):
            size = mesh.attributes.Size()
        else:
            size = mesh.bdr_attributes.Size()
     
        arr = [0]*size
        if idx is None: idx = self._sel_index
        for k in idx: arr[k-1] = 1
        return intArray(arr)

    def restrict_coeff(self, coeff, engine, vec = False, matrix = False, idx=None):
        if len(self._sel_index) == 1 and self._sel_index[0] == -1:
           return coeff
        arr = self.get_restriction_array(engine, idx)
#        arr.Print()
        if vec:
            return mfem.VectorRestrictedCoefficient(coeff, arr)
        elif matrix:
            return mfem.MatrixRestrictedCoefficient(coeff, arr)           
        else:
            return mfem.RestrictedCoefficient(coeff, arr)

    def get_essential_idx(self, idx):
        '''
        return index of essentail bdr for idx's fespace
        '''
        raise NotImplementedError(
             "you must specify this method in subclass")

    def get_root_phys(self):
        p = self
        while isinstance(p.parent, Phys):
           p = p.parent
        return p
        
    def get_exter_NDoF(self, kfes=0):
        return 0
    
    def has_extra_DoF(self, kfes=0):
        return False

    def update_param(self):
        ''' 
        called everytime it assembles either matrix or rhs
        '''
        pass
     
    def postprocess_extra(self, sol, flag, sol_extra):
        '''
        postprocess extra (Lagrange multiplier) segment
        of solutions. 
        
        sol_extra is a dictionary in which this method 
        will add processed data (dataname , value).
        '''   
        raise NotImplementedError(
             "you must specify this method in subclass")
       
    def has_bf_contribution(self, kfes):
        return False
    
    def has_lf_contribution(self, kfes):
        return False
     
    def has_interpolation_contribution(self, kfes):
        return False
     
    def has_mixed_contribution(self):
        return False

    def get_mixedbf_loc(self):
        '''
        r, c, and flag of MixedBilinearForm
        flag -1 :  use conjugate when building block matrix
        '''
        return []

    def add_bf_contribution(self, engine, a, real=True, **kwargs):
        raise NotImplementedError(
             "you must specify this method in subclass")

    def add_lf_contribution(self, engine, b, real=True, **kwargs):        
        raise NotImplementedError(
             "you must specify this method in subclass")

    def add_extra_contribution(self, engine, kfes, **kwargs):        
        ''' 
        return four elements
        M12, M21, M22, rhs
        '''
        raise NotImplementedError(
             "you must specify this method in subclass")

    def add_interplation_contribution(self, engine, **kwargs):        
        ''' 
        P^t A P y = P^t f, x = Py
        return P, nonzero, zero diagonals.
        '''
        raise NotImplementedError(
             "you must specify this method in subclass")
     
    def apply_essential(self, engine, gf, **kwargs):
        raise NotImplementedError(
             "you must specify this method in subclass")

    def get_init_coeff(self, engine, **kwargs):
        return None
     
    def apply_init(self, engine, gf, **kwargs):
        import warnings
        warnings.warn("apply init is not implemented to " + str(self))
        
    def add_mix_contribution(self, engine, a, r, c, is_trans, real=True):
        '''
        return array of crossterms
        [[vertical block elements], [horizontal block elements]]
        array length must be the number of fespaces
        for the physics
 
        r, c : r,c of block matrix
        is_trans: indicate if transposed matrix is filled
        '''
        raise NotImplementedError(
             "you must specify this method in subclass")


    def add_variables(self, solvar, n, solr, soli = None):
        '''
        add model variable so that a user can interept simulation 
        results. It is also used in cross-physics interaction.

        '''
        pass
    def add_domain_variables(self, v, n, suffix, ind_vars, solr, soli = None):
        pass
    def add_bdr_variables(self, v, n, suffix, ind_vars, solr, soli = None):
        pass

    def panel1_param(self):
        return self.vt.panel_param(self)
        
    def get_panel1_value(self):
        return self.vt.get_panel_value(self)

    def preprocess_params(self, engine):
        self.vt.preprocess_params(self)
        self.vt3.preprocess_params(self)               
        return

    def import_panel1_value(self, v):
        return self.vt.import_panel_value(self, v)

    def panel1_tip(self):
        return self.vt.panel_tip()

    def panel3_param(self):
        from petram.pi.widget_nl import NonlinearTermPanel
        l = self.vt3.panel_param(self)
        if self.hide_nl_panel or len(self.nlterms)==0:
           return l
        setting = {'UI':NonlinearTermPanel, 'names':self.nlterms}
        l.append([None, None, 99, setting])
        return l
        
    def get_panel3_value(self):
        if self.hide_nl_panel or len(self.nlterms)==0:
            return self.vt3.get_panel_value(self)
        else:
            return self.vt3.get_panel_value(self) + [self.nl_config]
    
    def import_panel3_value(self, v):
        if self.hide_nl_panel or len(self.nlterms)==0:
            self.vt3.import_panel_value(self, v)
        else:
            self.vt3.import_panel_value(self, v[:-1])
            self.nl_config = v[-1]

    def panel3_tip(self):
        if self.hide_nl_panel or len(self.nlterms)==0:
            return self.vt3.panel_tip()
        else:
            return self.vt3.panel_tip() +[None]
         
    @property
    def geom_dim(self):
        root_phys = self.get_root_phys()
        return root_phys.geom_dim
    @property
    def dim(self):
        root_phys = self.get_root_phys()
        return root_phys.dim        

    def add_integrator(self, engine, name, coeff, adder, integrator, idx=None, vt=None):
        if coeff is None: return
        if vt is None: vt = self.vt
        #if vt[name].ndim == 0:
        if isinstance(coeff, mfem.Coefficient):
            coeff = self.restrict_coeff(coeff, engine, idx=idx)
        elif isinstance(coeff, mfem.VectorCoefficient):          
            coeff = self.restrict_coeff(coeff, engine, vec = True, idx=idx)
        elif isinstance(coeff, mfem.MatrixCoefficient):                     
            coeff = self.restrict_coeff(coeff, engine, matrix = True, idx=idx)
        else:
            assert  False, "Unknown coefficient type: " + str(type(coeff))
        adder(integrator(coeff))
        
    def onItemSelChanged(self, evt):
        '''
        GUI response when model object is selected in
        the dlg_edit_model
        '''
        viewer = evt.GetEventObject().GetTopLevelParent().GetParent()
        viewer.set_view_mode('phys',  self)

class PhysModule(Phys):
    hide_ns_menu = False
    dim_fixed = True # if ndim of physics is fixed
    @property
    def geom_dim(self):
        return len(self.ind_vars.split(','))       
    @property
    def dim(self):
        return self.ndim        
    @dim.setter
    def dim(self, value):
        self.ndim = value
       
    def attribute_set(self, v):
        v = super(PhysModule, self).attribute_set(v)
        v["order"] = 1
        v["element"] = 'H1_FECollection'
        v["ndim"] = 2 #logical dimension (= ndim of mfem::Mesh)
        v["ind_vars"] = 'x, y'
        v["dep_vars_suffix"] = ''
        v["mesh_idx"] = 0
        v['sel_index'] = ['all']
        return v
     
    def panel1_param(self):
        return [["mesh num.",   self.mesh_idx, 400, {}],
                ["element",self.element,  2,   {}],
                ["order",  self.order,    400, {}],]
     
    def panel1_tip(self):
        return ["index of mesh", "element type", "element order"]
     
    def get_panel1_value(self):                
        return [self.mesh_idx, self.element, self.order]
     
    def import_panel1_value(self, v):
        self.mesh_idx = long(v[0])
        self.element = str(v[1])
        self.order = long(v[2])
        return v[3:]
     
    def panel2_param(self):

        if self.geom_dim == 3:
           choice = ("Volume", "Surface", "Edge")
        elif self.geom_dim == 2:
           choice = ("Surface", "Edge")
           
        p = ["Type", choice[0], 4,
             {"style":wx.CB_READONLY, "choices": choice}]
        if self.dim_fixed:
            return [["index",  'all',  0,   {'changing_event':True,
                                            'setfocus_event':True}, ]]
        else:
            return [p, ["index",  'all',  0,   {'changing_event':True,
                                            'setfocus_event':True}, ]]
              
    def get_panel2_value(self):
        choice = ["Point", "Edge", "Surface", "Volume",]
        if self.dim_fixed:
            return ','.join(self.sel_index)
        else:
            return choice[self.dim], ','.join(self.sel_index)
     
    def import_panel2_value(self, v):
        if self.dim_fixed:        
            arr =  str(v[0]).split(',')
        else:
           if str(v[0]) == "Volume":
              self.dim = 3
           elif str(v[0]) == "Surface":
              self.dim = 2
           elif str(v[0]) == "Edge":
              self.dim = 1                      
           else:
              self.dim = 1                                 
           arr =  str(v[1]).split(',')
           
        arr = [x for x in arr if x.strip() != '']
        self.sel_index = arr
       
    @property
    def dep_vars(self):
        raise NotImplementedError(
             "you must specify this method in subclass")

    @property
    def dep_vars_base(self, name):
        raise NotImplementedError(
             "you must specify this method in subclass")

    def dep_var_index(self, name):
        return self.dep_vars.index(name)

    def check_new_fespace(fespaces, meshes):
        mesh = meshes[self.mesh_name]
        fespacs = fespeces[self]

    def get_fec(self):
        name = self.dep_vars
        return [(name[0], self.element)]
     
    def is_complex(self):
        return False
     
    def soldict_to_solvars(self, soldict, variables):
        keys = soldict.keys()
        depvars = self.dep_vars
        suffix = self.dep_vars_suffix
        ind_vars = [x.strip() for x in self.ind_vars.split(',')]
        
        for k in keys:
            n = k.split('_')[0]
            if n in depvars:
               sol = soldict[k]
               solr = sol[0]
               soli = sol[1] if len(sol) > 1 else None
               self.add_variables(variables, n, solr, soli)
               
               # collect all definition from children
               for mm in self.walk():
                  if not mm.enabled: continue
                  if mm is self: continue
                  mm.add_domain_variables(variables, n, suffix, ind_vars,
                                    solr, soli)
                  mm.add_bdr_variables(variables, n, suffix, ind_vars,
                                    solr, soli)

    def onItemSelChanged(self, evt):
        '''
        GUI response when model object is selected in
        the dlg_edit_model
        '''
        viewer = evt.GetEventObject().GetTopLevelParent().GetParent()
        viewer.set_view_mode('phys',  self)

    def is_viewmode_grouphead(self):
        return True
         


        
