import json, uuid, re

_J = None

def _open_jmap():
    """The modkit's reflection dump (Content/DynamicClasses/Whiskerwood-*.jmap.gz).
    Set JMAP=/path/to/file.jmap(.gz) to override; default looks in ../Whiskerwood-Project."""
    import glob, gzip, os
    p = os.environ.get('JMAP')
    if not p:
        here = os.path.dirname(os.path.abspath(__file__))
        c = sorted(glob.glob(os.path.join(here, '..', '..', 'Whiskerwood-Project', 'Content', 'DynamicClasses', '*.jmap*')))
        if not c:
            raise SystemExit('jmap not found: set JMAP=path/to/Whiskerwood-x.jmap.gz')
        p = c[-1]
    return gzip.open(p, 'rt', encoding='utf-8') if p.endswith('.gz') else open(p, encoding='utf-8')
def J():
    global _J
    if _J is None:
        _J = json.load(_open_jmap())['objects']
    return _J

def gid():
    return uuid.uuid4().hex.upper()

def cls_ref(path):
    return "/Script/CoreUObject.Class'%s'" % path

def bp_cls_ref(asset):  # asset '/Game/Mods/X/WBP_A'
    n = asset.split('/')[-1]
    return "/Script/UMG.WidgetBlueprintGeneratedClass'%s.%s_C'" % (asset, n)

# ---- pin types -------------------------------------------------------------
def T(cat, sub='', obj=None, cont='None', ref=False, const=False, wrapper=False):
    return dict(cat=cat, sub=sub, obj=obj, cont=cont, ref=ref, const=const, wrapper=wrapper)

EXEC = T('exec')
BOOL = T('bool'); INT = T('int'); STR = T('string'); NAME = T('name'); TEXT = T('text')
DBL = T('real', 'double'); FLT = T('real', 'float')
def OBJ(path): return T('object', obj=cls_ref(path) if path.startswith('/Script/') else path)
def CLS(meta): return T('class', obj=cls_ref(meta), wrapper=True)
def STRUCT(path): return T('struct', obj="/Script/CoreUObject.ScriptStruct'%s'" % path)
def ENUM(path): return T('byte', obj="/Script/CoreUObject.Enum'%s'" % path)
def ARR(t): d = dict(t); d['cont'] = 'Array'; return d
def SET(t): d = dict(t); d['cont'] = 'Set'; return d

def prop_type(p):
    t = p['type']
    if t == 'BoolProperty': r = BOOL
    elif t == 'IntProperty': r = INT
    elif t == 'FloatProperty': r = FLT
    elif t == 'DoubleProperty': r = DBL
    elif t == 'StrProperty': r = STR
    elif t == 'NameProperty': r = NAME
    elif t == 'TextProperty': r = TEXT
    elif t in ('ObjectProperty', 'WeakObjectProperty'): r = OBJ(p['property_class'])
    elif t == 'ClassProperty': r = CLS(p.get('meta_class') or '/Script/CoreUObject.Object')
    elif t == 'StructProperty': r = STRUCT(p['struct'])
    elif t == 'EnumProperty': r = ENUM(p['enum'])
    elif t == 'ByteProperty': r = ENUM(p['enum']) if p.get('enum') else T('byte')
    elif t == 'ArrayProperty': r = ARR(prop_type(p['inner']))
    elif t == 'SetProperty': r = SET(prop_type(p['key_prop']))
    else: raise Exception('unknown prop type ' + t)
    return dict(r)

# ---- nodes -----------------------------------------------------------------
class Pin:
    def __init__(self, node, name, t, out=False, default=None, defobj=None, hidden=False, friendly=None):
        self.node = node; self.name = name; self.t = dict(t); self.out = out
        self.default = default; self.defobj = defobj; self.hidden = hidden
        self.friendly = friendly; self.id = gid(); self.links = []
    def fmt(self):
        t = self.t
        s = 'CustomProperties Pin (PinId=%s,PinName="%s",' % (self.id, self.name)
        if self.friendly: s += 'PinFriendlyName=%s,' % self.friendly
        if self.out: s += 'Direction="EGPD_Output",'
        s += 'PinType.PinCategory="%s",PinType.PinSubCategory="%s",' % (t['cat'], t['sub'])
        s += 'PinType.PinSubCategoryObject=%s,' % ('"%s"' % t['obj'] if t['obj'] else 'None')
        s += 'PinType.PinSubCategoryMemberReference=(),PinType.PinValueType=(),'
        s += 'PinType.ContainerType=%s,' % t['cont']
        s += 'PinType.bIsReference=%s,PinType.bIsConst=%s,PinType.bIsWeakPointer=False,PinType.bIsUObjectWrapper=%s,PinType.bSerializeAsSinglePrecisionFloat=False,' % (
            bool(t['ref']), bool(t['const']), bool(t['wrapper']))
        if self.default is not None: s += 'DefaultValue="%s",' % self.default
        if self.defobj is not None: s += 'DefaultObject="%s",' % self.defobj
        if self.links: s += 'LinkedTo=(%s),' % ''.join('%s %s,' % (p.node.name, p.id) for p in self.links)
        s += 'PersistentGuid=00000000000000000000000000000000,bHidden=%s,bNotConnectable=False,bDefaultValueIsReadOnly=False,bDefaultValueIsIgnored=False,bAdvancedView=False,bOrphanedPin=False,)' % self.hidden
        return s

class Node:
    def __init__(self, g, cls, name, header):
        self.g = g; self.cls = cls; self.name = name; self.header = header
        self.pins = []; self.x = 0; self.y = 0; self.extra = []
    def pin(self, name, t, **kw):
        p = Pin(self, name, t, **kw); self.pins.append(p); return p
    def __getitem__(self, k):
        for p in self.pins:
            if p.name == k: return p
        raise KeyError('%s has no pin %s (has %s)' % (self.name, k, [p.name for p in self.pins]))
    def set(self, pin, val):
        p = self[pin]
        if p.t['cat'] in ('object', 'class') and p.t['cont'] == 'None':
            p.defobj = val
        else:
            p.default = val
        return self
    def fmt(self):
        short = self.cls.split('.')[-1]
        lines = ['Begin Object Class=%s Name="%s" ExportPath="%s\'%s.%s:EventGraph.%s\'"' % (
            self.cls, self.name, self.cls, self.g.asset, self.g.asset.split('/')[-1], self.name)]
        lines += ['   ' + h for h in self.header]
        lines += ['   NodePosX=%d' % self.x, '   NodePosY=%d' % self.y, '   NodeGuid=%s' % gid()]
        lines += ['   ' + e for e in self.extra]
        lines += ['   ' + p.fmt() for p in self.pins]
        lines.append('End Object')
        return '\n'.join(lines)

BG = '/Script/BlueprintGraph.'

class Graph:
    def __init__(self, asset):
        self.asset = asset; self.nodes = []; self.names = set()
        self.col = 0; self.row = 0
    def _name(self, n):
        base = n; i = 1
        while n in self.names: i += 1; n = '%s%d' % (base, i)
        self.names.add(n); return n
    def add(self, cls, name, header, x=None, y=None):
        n = Node(self, cls, self._name(name), header)
        n.x = x if x is not None else 0; n.y = y if y is not None else 0
        self.nodes.append(n); return n
    # --- generic native call from jmap
    def call(self, fpath, name=None, x=0, y=0, pure=None, array=False, **defaults):
        o = J()[fpath]
        owner, fn = fpath.split(':')
        flags = o['function_flags']
        is_static = 'FUNC_Static' in flags
        is_pure = ('FUNC_BlueprintPure' in flags) if pure is None else pure
        cls = BG + ('K2Node_CallArrayFunction' if array else 'K2Node_CallFunction')
        hdr = []
        if is_pure and array: hdr.append('bDefaultsToPureFunc=True')
        hdr.append('FunctionReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), fn))
        n = self.add(cls, name or fn, hdr, x, y)
        if not is_pure:
            n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
        dflt = owner.rsplit('.', 1)[0] + '.Default__' + owner.rsplit('.', 1)[1]
        if is_static:
            n.pin('self', OBJ(owner), defobj=dflt, hidden=True, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
        else:
            n.pin('self', OBJ(owner), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
        for p in o['properties']:
            fl = p['flags']
            t = prop_type(p)
            ret = 'CPF_ReturnParm' in fl
            outp = 'CPF_OutParm' in fl and 'CPF_ReferenceParm' not in fl
            if 'CPF_ReferenceParm' in fl and not ret: t['ref'] = True
            if 'CPF_ConstParm' in fl and not ret and not outp: t['const'] = True
            hidden = p['name'] in ('WorldContext', 'WorldContextObject')
            d = None
            if not (ret or outp):
                if t['cat'] == 'bool': d = 'false'
                elif t['cat'] == 'int': d = '0'
                elif t['cat'] == 'real': d = '0.0'
                elif t['cat'] in ('string', 'name'): d = ''
            n.pin(p['name'], t, out=ret or outp, default=d, hidden=hidden)
        for k, v in defaults.items():
            n.set(k, v)
        return n
    def bpcall(self, asset, fn, params, name=None, x=0, y=0):
        """call a custom event on another widget BP: params list of (name, type)"""
        cref = bp_cls_ref(asset)
        n = self.add(BG + 'K2Node_CallFunction', name or fn,
                     ['FunctionReference=(MemberParent="%s",MemberName="%s")' % (cref, fn)], x, y)
        n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
        n.pin('self', T('object', obj=cref), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
        for pn, pt in params: n.pin(pn, pt)
        return n
    def event(self, owner, ev, outs, name=None, x=0, y=0):
        n = self.add(BG + 'K2Node_Event', name or ev,
                     ['EventReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), ev), 'bOverrideFunction=True'], x, y)
        n.pin('OutputDelegate', T('delegate'), out=True)
        n.pin('then', EXEC, out=True)
        for pn, pt in outs: n.pin(pn, pt, out=True)
        return n
    def custom_event(self, fname, inputs, x=0, y=0):
        n = self.add(BG + 'K2Node_CustomEvent', fname, ['CustomFunctionName="%s"' % fname], x, y)
        for pn, pt in inputs:
            s = 'PinCategory="%s"' % pt['cat']
            if pt['sub']: s += ',PinSubCategory="%s"' % pt['sub']
            if pt['obj']: s += ',PinSubCategoryObject="%s"' % pt['obj']
            n.extra.append('CustomProperties UserDefinedPin (PinName="%s",PinType=(%s),DesiredPinDirection=EGPD_Output)' % (pn, s))
        n.pin('OutputDelegate', T('delegate'), out=True)
        n.pin('then', EXEC, out=True)
        for pn, pt in inputs: n.pin(pn, pt, out=True)
        return n
    def get(self, var, t, x=0, y=0, owner=None, name=None):
        if owner:
            hdr = 'VariableReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), var)
        else:
            hdr = 'VariableReference=(MemberName="%s",bSelfContext=True)' % var
        n = self.add(BG + 'K2Node_VariableGet', name or (var + 'Get'), [hdr], x, y)
        n.pin(var, t, out=True)
        if owner: n.pin('self', OBJ(owner), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
        return n
    def setv(self, var, t, x=0, y=0, value=None, name=None):
        n = self.add(BG + 'K2Node_VariableSet', name or ('Set' + var),
                     ['VariableReference=(MemberName="%s",bSelfContext=True)' % var], x, y)
        n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
        p = n.pin(var, t)
        if value is not None:
            if t['cat'] in ('object', 'class'): p.defobj = value
            else: p.default = value
        n.pin('Output_Get', t, out=True)
        return n
    def branch(self, x=0, y=0, name='Br'):
        n = self.add(BG + 'K2Node_IfThenElse', name, [], x, y)
        n.pin('execute', EXEC); n.pin('Condition', BOOL, default='true')
        n.pin('then', EXEC, out=True, friendly='NSLOCTEXT("K2Node", "true", "true")')
        n.pin('else', EXEC, out=True, friendly='NSLOCTEXT("K2Node", "false", "false")')
        return n
    def macro(self, which, elem_t=None, x=0, y=0, name=None):
        guid = {'ForEachLoop': '99DBFD5540A796041F72A5A9DA655026'}.get(which, '00000000000000000000000000000000')
        n = self.add(BG + 'K2Node_MacroInstance', name or which,
                     ['MacroGraphReference=(MacroGraph="/Script/Engine.EdGraph\'/Engine/EditorBlueprintResources/StandardMacros.StandardMacros:%s\'",GraphBlueprint="/Script/Engine.Blueprint\'/Engine/EditorBlueprintResources/StandardMacros.StandardMacros\'",GraphGuid=%s)' % (which, guid)], x, y)
        if which in ('ForEachLoop', 'ForEachLoopWithBreak'):
            n.pin('Exec', EXEC); n.pin('Array', ARR(elem_t))
            if which == 'ForEachLoopWithBreak': n.pin('Break', EXEC)
            n.pin('LoopBody', EXEC, out=True); n.pin('Array Element', elem_t, out=True)
            n.pin('Array Index', INT, out=True); n.pin('Completed', EXEC, out=True)
        elif which == 'WhileLoop':
            n.pin('Exec', EXEC); n.pin('Condition', BOOL, default='false')
            n.pin('LoopBody', EXEC, out=True); n.pin('Completed', EXEC, out=True)
        return n
    def create_widget(self, asset, x=0, y=0, name='Create'):
        cref = bp_cls_ref(asset)
        n = self.add('/Script/UMGEditor.K2Node_CreateWidget', name, [], x, y)
        n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
        n.pin('Class', T('class', obj=cls_ref('/Script/UMG.UserWidget')), defobj='%s.%s_C' % (asset, asset.split('/')[-1]))
        n.pin('OwningPlayer', OBJ('/Script/Engine.PlayerController'))
        n.pin('ReturnValue', T('object', obj=cref), out=True)
        return n
    def cast(self, target, pure, x=0, y=0, name='Cast'):
        hdr = ['TargetType="%s"' % cls_ref(target)]
        if pure: hdr.append('bIsPureCast=True')
        n = self.add(BG + 'K2Node_DynamicCast', name, hdr, x, y)
        if not pure:
            n.pin('execute', EXEC); n.pin('then', EXEC, out=True); n.pin('CastFailed', EXEC, out=True)
        n.pin('Object', OBJ('/Script/CoreUObject.Object'))
        disp = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', target.split('.')[-1])
        n.pin('As' + disp, OBJ(target), out=True)
        n.pin('bSuccess', BOOL, out=True, hidden=not pure)
        return n
    def arr(self, fn, elem_t, x=0, y=0, name=None, pure=False):
        """KismetArrayLibrary wildcard call with explicit element type"""
        cls = BG + 'K2Node_CallArrayFunction'
        hdr = []
        if pure: hdr.append('bDefaultsToPureFunc=True')
        hdr.append('FunctionReference=(MemberParent="%s",MemberName="%s")' % (cls_ref('/Script/Engine.KismetArrayLibrary'), fn))
        n = self.add(cls, name or fn, hdr, x, y)
        if not pure: n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
        n.pin('self', OBJ('/Script/Engine.KismetArrayLibrary'), defobj='/Script/Engine.Default__KismetArrayLibrary', hidden=True, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
        at = ARR(elem_t); at['ref'] = True
        n.pin('TargetArray', at)
        if fn == 'Array_Add':
            it = dict(elem_t); it['ref'] = True; it['const'] = True
            n.pin('NewItem', it); n.pin('ReturnValue', INT, out=True)
        elif fn == 'Array_Length':
            n.pin('ReturnValue', INT, out=True)
        return n
    def text(self):
        # auto layout: keep given x/y
        return '\n'.join(n.fmt() for n in self.nodes) + '\n'

def link(a, b):
    """a: output pin, b: input pin (order-insensitive)"""
    a.links.append(b); b.links.append(a)

def chain(*nodes):
    """link then->execute through a sequence of (node or (node,pin)) items"""
    prev = None
    for it in nodes:
        if prev is not None:
            src = prev if isinstance(prev, Pin) else prev['then']
            dst = it if isinstance(it, Pin) else it['execute']
            link(src, dst)
        prev = it if not isinstance(it, Pin) else None
        if isinstance(it, Pin):
            prev = it.node if it.name in ('execute', 'Exec') else it
    return nodes[-1]

def ex(a, b, apin='then', bpin='execute'):
    link(a[apin] if isinstance(a, Node) else a, b[bpin] if isinstance(b, Node) else b)
