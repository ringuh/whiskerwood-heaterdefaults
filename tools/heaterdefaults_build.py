"""Generates the Blueprint paste text (T3D) for HeaterDefaults into tools/out/.
Usage: python tools/heaterdefaults_build.py   (needs the modkit's jmap, see t3d.py)
Paste each file into the matching asset's event graph (Ctrl+A, Delete, Ctrl+V), compile.
The Heater / bonfire classes are loaded from their path strings, so no dropdowns need setting.

How the mod works (game 0.7.207):
- Every FueledHeater keeps its "Turn on at" limit as a heat byte. The game default is the
  same for every heater type (10 C) and lives in no data table, so it is set per heater.
- UI_HeaterView's native ReceiveHudAction handles action "setAutopauseLimit": paramInt = new
  limit (heat units), paramGrid = building root cell, for the heater that is the view's
  Context. It sends the same sim action as the window's - / + buttons. Context is not
  Blueprint-writable, so it is set with SetObjectPropertyByName.
- BP_MapLoad, no tick and no looping timer:
  * BeginPlay and onLoadingFinished: remember every existing Heating Stove / Bonfire (changes nothing).
    BeginPlay covers new games (onLoadingFinished doesn't reach BP_MapLoad there).
  * onBuildingSpawned (instantly placed buildings, e.g. the Radiator): handles that one actor.
  * onConstructionSpawned: binds the site's OnDestroyed; when the site goes (finished or
    cancelled) a one-shot 1 s timer lists only Heater_C and bonfire_C actors and handles the
    ones not seen before; if none is new it retries up to 3 times, 1 s apart.
  * A heater still at the game default gets limit = (C + 30) * 3 + HeatIncrementU8
    (HeatSystem: MinimumTemperature -30, HeatPerDegreeCelsius 3).
  (ModAPI.onBuildingSpawned does not fire for buildings finished via construction in 0.7.207.)
- Log lines (modlog.txt) are written only when Saved\\mods\\HeaterDefaultsConfig\\debug.txt exists and is not empty.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from t3d import *

OUT = os.path.join(os.path.dirname(__file__), 'out')
os.makedirs(OUT, exist_ok=True)
M = '/Game/Mods/HeaterDefaults/'
STARTUP, MAPLOAD = M + 'BP_Startup', M + 'BP_MapLoad'
KSL = '/Script/Engine.KismetSystemLibrary'
KML = '/Script/Engine.KismetMathLibrary'
KSTR = '/Script/Engine.KismetStringLibrary'
API = '/Script/SystemCore.ModAPI'
PA = '/Script/ProjectArco.'
GA, FH, VIEWC, AWB = PA + 'GridActor', PA + 'FueledHeater', PA + 'UI_HeaterView', PA + 'ArcoWidgetBase'
OPT_ID = 'HeaterDefaults_TurnOnAt'
VALUES = [str(v) for v in range(-30, 31, 5)]
DEFAULT = '0'


def modapi(g, x, y, name='Api'):
    return g.call(API + ':GetModAPI', name, x, y)


def api_call(g, fn, x, y, name=None, **kw):
    a = modapi(g, x - 250, y + 150, name=(name or fn) + 'Api')
    n = g.call(API + ':' + fn, name or fn, x, y, **kw)
    link(a['ReturnValue'], n['self'])
    return n


class _Gate(Node):
    """Exec block 'if Debug: LogMessage', joined again by a reroute knot. Not a graph node itself."""
    def __init__(self, entry, exit_):
        self._e, self._x = entry, exit_; self.name = entry.node.name
    def __getitem__(self, k):
        return {'execute': self._e, 'then': self._x}[k]


def log(g, x, y, msg_pin=None, msg=None, name='Log'):
    """Debug-only log line: runs only when the Debug variable is true (debug.txt next to the pak)."""
    dg = g.get('Debug', BOOL, x - 200, y + 120, name=name + 'DebugGet')
    br = g.branch(x - 150, y, name + 'IfDebug'); link(dg['Debug'], br['Condition'])
    n = api_call(g, 'LogMessage', x, y, name=name, doPrependDate='true')
    if msg_pin: link(msg_pin, n['Msg'])
    elif msg: n.set('Msg', msg)
    ex(br, n)
    k = g.add(BG + 'K2Node_Knot', name + 'Join', [], x + 250, y - 40)
    k.pin('InputPin', EXEC); k.pin('OutputPin', EXEC, out=True)
    link(n['then'], k['InputPin']); link(br['else'], k['InputPin'])
    return _Gate(br['execute'], k['OutputPin'])


def class_cast(g, x, y, name):
    """Cast To Actor Class (K2Node_ClassDynamicCast), impure."""
    n = g.add(BG + 'K2Node_ClassDynamicCast', name, ['TargetType="%s"' % cls_ref('/Script/Engine.Actor')], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True); n.pin('CastFailed', EXEC, out=True)
    n.pin('Class', CLS('/Script/CoreUObject.Object'))
    n.pin('AsActor', CLS('/Script/Engine.Actor'), out=True)
    n.pin('bSuccess', BOOL, out=True, hidden=True)
    return n


def concat(g, x, y, *parts):
    cur = None
    for i, p in enumerate(parts):
        if cur is None:
            if isinstance(p, str):
                c = g.call(KSTR + ':Concat_StrStr', 'Cat', x, y); c.set('A', p); cur = c['ReturnValue']; continue
            cur = p; continue
        c = g.call(KSTR + ':Concat_StrStr', 'Cat', x + 40 * i, y + 30 * i)
        link(cur, c['A'])
        if isinstance(p, str): c.set('B', p)
        else: link(p, c['B'])
        cur = c['ReturnValue']
    return cur


def is_valid(g, pin, x, y, name='Valid'):
    n = g.call(KSL + ':IsValid', name, x, y); link(pin, n['Object']); return n['ReturnValue']


def set_on(g, owner, var, t, x, y, name):
    """VariableSet of a member on another object (Target pin)."""
    n = g.add(BG + 'K2Node_VariableSet', name,
              ['VariableReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), var)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin(var, t)
    n.pin('Output_Get', t, out=True)
    n.pin('self', OBJ(owner), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    return n


def struct_node(g, kind, spath, show, x, y, name):
    """kind 'Make' or 'Break'; show = list of property names to expose."""
    props = J()[spath]['properties']
    n = g.add(BG + 'K2Node_%sStruct' % kind, name,
              ['StructType="/Script/CoreUObject.ScriptStruct\'%s\'"' % spath, 'bMadeAfterOverridePinRemoval=True'], x, y)
    for i, p in enumerate(props):
        n.header.append('ShowPinForProperties(%d)=(PropertyName="%s",bShowPin=%s,bCanToggleVisibility=True)' % (i, p['name'], p['name'] in show))
    sname = spath.split('.')[-1]
    if kind == 'Break':
        n.pin(sname, STRUCT(spath))
    for p in props:
        if p['name'] in show:
            d = None
            if kind == 'Make':
                t = p['type']
                d = {'IntProperty': '0', 'StrProperty': '', 'BoolProperty': 'false'}.get(t)
            n.pin(p['name'], prop_type(p), out=(kind == 'Break'), default=d)
    if kind == 'Make':
        n.pin(sname, STRUCT(spath), out=True)
    return n


def array_contains(g, elem_t, x, y, name='Contains'):
    n = g.add(BG + 'K2Node_CallArrayFunction', name, ['bDefaultsToPureFunc=True',
        'FunctionReference=(MemberParent="%s",MemberName="Array_Contains")' % cls_ref('/Script/Engine.KismetArrayLibrary')], x, y)
    n.pin('self', OBJ('/Script/Engine.KismetArrayLibrary'), defobj='/Script/Engine.Default__KismetArrayLibrary', hidden=True, friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    at = ARR(elem_t); at['ref'] = True; at['const'] = True
    it = dict(elem_t); it['ref'] = True; it['const'] = True
    n.pin('TargetArray', at); n.pin('ItemToFind', it); n.pin('ReturnValue', BOOL, out=True)
    return n


# =========================================================================== BP_Startup
g = Graph(STARTUP)
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, 0)
vals = g.add(BG + 'K2Node_MakeArray', 'Vals', ['NumInputs=%d' % len(VALUES)], 300, 250)
vals.pin('Array', ARR(STR), out=True)
for i, v in enumerate(VALUES):
    vals.pin('[%d]' % i, STR, default=v)
reg = api_call(g, 'RegisterModOptions', 600, 0, name='Reg',
               optionId=OPT_ID,
               optionDisplayName='Heaters - default Turn on at (C)',
               DefaultValue=DEFAULT,
               optionDescription='Bonfires, Heating Stoves and Steam Heaters that are still at the game default (10 C) '
                                 'get this Turn on at temperature instead. Heaters you have adjusted yourself are left alone. '
                                 'Game default is 10.')
link(vals['Array'], reg['Values'])
ex(bp, reg)
open(OUT + '/BP_Startup.txt', 'w', encoding='utf-8').write(g.text())

# =========================================================================== BP_MapLoad (v17, heater only, new heaters only, no full scans, debug-gated logs, classes loaded from path)
# Variables: Debug (Boolean), View (UI_HeaterView ref), Known (Actor array), Retries (Integer), KnownBefore (Integer),
#            Cur (Actor ref), Built (Actor ref), SingleMode (Boolean), LoadScan (Boolean), Ready (Boolean) <- 1.1
g = Graph(MAPLOAD)
VIEW_T = OBJ(VIEWC); ACTOR = OBJ('/Script/Engine.Actor'); GAT = OBJ(GA)
HEATER_CLASSES = ['/Game/GridActors/Heater.Heater_C', '/Game/GridActors/bonfire.bonfire_C']  # Radiators arrive via onBuildingSpawned

_orig_fmt = Pin.fmt
def _fmt(self):
    s = _orig_fmt(self)
    mr = getattr(self, 'memref', None)
    if mr: s = s.replace('PinType.PinSubCategoryMemberReference=()', 'PinType.PinSubCategoryMemberReference=(%s)' % mr, 1)
    return s
Pin.fmt = _fmt

def bind(g, target_pin, owner, delegate, sig_pkg, sig, event_node, x, y, name):
    n = g.add(BG + 'K2Node_AddDelegate', name,
              ['DelegateReference=(MemberParent="%s",MemberName="%s")' % (cls_ref(owner), delegate)], x, y)
    n.pin('execute', EXEC); n.pin('then', EXEC, out=True)
    n.pin('self', OBJ(owner), friendly='NSLOCTEXT("K2Node", "Target", "Target")')
    d = n.pin('Delegate', T('delegate'))
    d.memref = 'MemberParent="/Script/CoreUObject.Package\'%s\'",MemberName="%s"' % (sig_pkg, sig)
    link(target_pin, n['self'])
    ev = event_node['OutputDelegate']
    ev.memref = 'MemberParent="/Script/Engine.BlueprintGeneratedClass\'%s.%s_C\'",MemberName="%s"' % (MAPLOAD, MAPLOAD.split('/')[-1], event_node.name)
    link(ev, d)
    return n

def self_node(g, x, y, name):
    n = g.add(BG + 'K2Node_Self', name, [], x, y)
    n.pin('self', T('object', sub='self'), out=True)
    return n

def set_timer(g, x, y, name):
    n = g.call(KSL + ':K2_SetTimer', name, x, y, FunctionName='OnScanTimer', Time='1.0', bLooping='false')
    link(self_node(g, x - 200, y + 200, name + 'Self')['self'], n['Object'])
    return n

def known_len(g, x, y, name):
    kg = g.get('Known', ARR(ACTOR), x, y, name=name + 'Get')
    ln = g.arr('Array_Length', ACTOR, x + 200, y, name=name, pure=True); link(kg['Known'], ln['TargetArray'])
    return ln['ReturnValue']

# ---- BeginPlay
bp = g.event('/Script/Engine.Actor', 'ReceiveBeginPlay', [], 'Begin', 0, -1800)
api = modapi(g, 200, -1550, name='BindApi')
evL = g.custom_event('OnLoaded', [], 0, -1300)
evC = g.custom_event('OnConstruction', [('Actor', ACTOR)], 0, -1000)
evG = g.custom_event('OnSiteGone', [('DestroyedActor', ACTOR)], 0, -700)
evB = g.custom_event('OnBuilt', [('Actor', ACTOR)], 0, -400)
evT = g.custom_event('OnScanTimer', [], 0, -100)
b1 = bind(g, api['ReturnValue'], API, 'onLoadingFinished', '/Script/SystemCore', 'ModAPI_OnEvent__DelegateSignature', evL, 400, -1800, 'BindLoaded'); ex(bp, b1)
b2 = bind(g, api['ReturnValue'], API, 'onConstructionSpawned', '/Script/SystemCore', 'ModAPI_OnActorSpawned__DelegateSignature', evC, 700, -1800, 'BindConstruction'); ex(b1, b2)
b4 = bind(g, api['ReturnValue'], API, 'onBuildingSpawned', '/Script/SystemCore', 'ModAPI_OnActorSpawned__DelegateSignature', evB, 1000, -1800, 'BindBuilt'); ex(b2, b4)

# ---- OnConstruction: watch the site
b3 = bind(g, evC['Actor'], '/Script/Engine.Actor', 'OnDestroyed', '/Script/Engine', 'ActorDestroyedSignature__DelegateSignature', evG, 400, -1000, 'BindSiteGone'); ex(evC, b3)
# ---- OnSiteGone: one-shot timer, 3 retries
sr = g.setv('Retries', INT, 400, -700, value='3', name='ArmRetries'); ex(evG, sr)
st = set_timer(g, 700, -700, 'StartScanTimer'); ex(sr, st)

# ---- entry points into PREP: SingleMode decides between "just this building" and "heater-class scan"
gcB = g.call('/Script/Engine.Actor:GetComponentByClass', 'BuiltHeater', 300, -250, ComponentClass=FH); link(evB['Actor'], gcB['self'])
gcB['ReturnValue'].t = OBJ(FH)
bB = g.branch(400, -400, 'BrBuiltIsHeater'); link(is_valid(g, gcB['ReturnValue'], 500, -250, 'BuiltValid'), bB['Condition']); ex(evB, bB)
sb = g.setv('Built', ACTOR, 650, -400, name='RememberBuilt'); link(evB['Actor'], sb['Built']); ex(bB, sb)
lsB = g.setv('LoadScan', BOOL, 800, -550, value='false', name='MarkBuiltScan'); ex(sb, lsB)
sm1 = g.setv('SingleMode', BOOL, 900, -400, value='true', name='ModeSingle'); ex(lsB, sm1)
# ---- Startup (1.1): a NEW game doesn't deliver onLoadingFinished to BP_MapLoad, so BeginPlay (after the binds)
#      and OnLoaded both come here. First time (Ready false): Ready = true, debug switch, "ready" log. Every time:
#      the remember-only load scan (records existing heaters, changes nothing). It runs again at onLoadingFinished on
#      purpose: at a save load BeginPlay may come before the save's buildings exist, and a heater missing from Known
#      would be changed by the next construction scan. Remembering twice is harmless (Known has no duplicates).
gr = g.branch(-300, -2300, 'BrReady'); link(g.get('Ready', BOOL, -450, -2150, name='ReadyGet')['Ready'], gr['Condition'])
ex(b4, gr); ex(evL, gr)
srd = g.setv('Ready', BOOL, -50, -2300, value='true', name='SetReady'); ex(gr, srd, 'else')
# Debug = Saved\\mods\\HeaterDefaultsConfig\\debug.txt (any text). ReadModTextFile adds '.txt' itself.
rdf = api_call(g, 'ReadModTextFile', 300, -2300, name='ReadDebugFile', modName='HeaterDefaultsConfig', Filename='debug'); ex(srd, rdf)
dfe = g.call(KSTR + ':IsEmpty', 'DebugFileEmpty', 550, -2150); link(rdf['ReturnValue'], dfe['InString'])
dfn = g.call(KML + ':Not_PreBool', 'DebugFileThere', 750, -2150); link(dfe['ReturnValue'], dfn['A'])
sdb = g.setv('Debug', BOOL, 600, -2300, name='SetDebug'); link(dfn['ReturnValue'], sdb['Debug']); ex(rdf, sdb)
l0 = log(g, 1100, -2300, msg='HeaterDefaults ready', name='LogReady'); ex(sdb, l0)
lsT = g.setv('LoadScan', BOOL, 250, -1300, value='true', name='MarkLoadScan'); ex(l0, lsT)
ex(gr, lsT)   # already set up: only the remember-only scan
sm0a = g.setv('SingleMode', BOOL, 400, -1300, value='false', name='ModeScanL'); ex(lsT, sm0a)
lsF = g.setv('LoadScan', BOOL, 250, -100, value='false', name='MarkBuildScan'); ex(evT, lsF)
sm0b = g.setv('SingleMode', BOOL, 400, -100, value='false', name='ModeScanT'); ex(lsF, sm0b)
kb = g.setv('KnownBefore', INT, 1150, -200, name='RememberCount'); link(known_len(g, 950, 0, 'CountBefore'), kb['KnownBefore'])
ex(sm1, kb); ex(sm0a, kb); ex(sm0b, kb)

# ---- PREP: view + option + limit
vg = g.get('View', VIEW_T, 1350, 50, name='ViewChk')
bv = g.branch(1450, -200, 'BrHaveView'); link(is_valid(g, vg['View'], 1400, 150, 'ViewValid'), bv['Condition']); ex(kb, bv)
pc = g.call('/Script/Engine.GameplayStatics:GetPlayerController', 'PC', 1500, 250)
cw = g.add('/Script/UMGEditor.K2Node_CreateWidget', 'CreateView', [], 1700, 50)
cw.pin('execute', EXEC); cw.pin('then', EXEC, out=True)
cw.pin('Class', T('class', obj=cls_ref('/Script/UMG.UserWidget')), defobj=VIEWC)
cw.pin('OwningPlayer', OBJ('/Script/Engine.PlayerController'))
cw.pin('ReturnValue', VIEW_T, out=True)
link(pc['ReturnValue'], cw['OwningPlayer']); ex(bv, cw, 'else')
sv = g.setv('View', VIEW_T, 2000, 50, name='SetView'); link(cw['ReturnValue'], sv['View']); ex(cw, sv)
opt = api_call(g, 'ReadModOptionValue', 2300, -200, name='ReadOpt', optionId=OPT_ID, fallbackValue=DEFAULT)
ex(bv, opt); ex(sv, opt)
tgt = g.call(KSTR + ':Conv_StringToInt', 'TargetC', 2600, 100); link(opt['ReturnValue'], tgt['InString'])
tune = api_call(g, 'ReadDataTableValue', 2600, -200, name='ReadInc', datatableName='SystemTunes', rowId='HeatIncrementU8', ColumnName='FloatValue')
ex(opt, tune)
incd = g.call(KSTR + ':Conv_StringToDouble', 'IncNum', 2900, 100); link(tune['ReturnValue'], incd['InString'])
inch = g.call(KML + ':Add_DoubleDouble', 'IncRound', 3100, 100, B='0.5'); link(incd['ReturnValue'], inch['A'])
inci = g.call(KML + ':FTrunc', 'IncInt', 3300, 100); link(inch['ReturnValue'], inci['A'])
incok = g.call(KML + ':Greater_IntInt', 'IncOK', 3500, 200, B='0'); link(inci['ReturnValue'], incok['A'])
inc = g.call(KML + ':SelectInt', 'IncSafe', 3700, 100, B='15'); link(inci['ReturnValue'], inc['A']); link(incok['ReturnValue'], inc['bPickA'])
t30 = g.call(KML + ':Add_IntInt', 'Plus30', 2900, 300, B='30'); link(tgt['ReturnValue'], t30['A'])
t3 = g.call(KML + ':Multiply_IntInt', 'Times3', 3100, 300, B='3'); link(t30['ReturnValue'], t3['A'])
lim = g.call(KML + ':Add_IntInt', 'Limit', 3900, 250); link(t3['ReturnValue'], lim['A']); link(inc['ReturnValue'], lim['B'])

smg = g.get('SingleMode', BOOL, 2900, -350, name='SingleModeGet')
bm = g.branch(2950, -200, 'BrSingle'); link(smg['SingleMode'], bm['Condition']); ex(tune, bm)

# ---- PROCESS(Cur): shared by single mode and the class loops
CUR_T = ACTOR
proc_entry_nodes = []
def set_cur(g, pin, x, y, name):
    n = g.setv('Cur', CUR_T, x, y, name=name); link(pin, n['Cur']); return n

# single mode: cast Built to GridActor -> Cur
bg_ = g.get('Built', ACTOR, 3200, -500, name='BuiltGet')
scS = set_cur(g, bg_['Built'], 3600, -650, 'CurFromBuilt'); ex(bm, scS)
proc_entry_nodes.append(scS)

# class loops: Heater_C, bonfire_C, Radiator_C, each LoopBody -> Cur = element -> PROCESS
# The class comes from its path string (class pins pointing at game Blueprints paste empty):
# MakeSoftClassPath -> soft class ref -> LoadClassAsset_Blocking -> Cast To Actor Class -> GetAllActorsOfClass.
prev = [(bm, 'else')]
for i, cpath in enumerate(HEATER_CLASSES):
    X = 3200 + 1400 * i
    scp = g.call(KSL + ':MakeSoftClassPath', 'ClassPath%d' % i, X, -1300, PathString=cpath)
    scr = g.call(KSL + ':Conv_SoftClassPathToSoftClassRef', 'ClassRef%d' % i, X + 250, -1300); link(scp['ReturnValue'], scr['SoftClassPath'])
    lca = g.call(KSL + ':LoadClassAsset_Blocking', 'LoadClass%d' % i, X, -1100); link(scr['ReturnValue'], lca['AssetClass'])
    for n_, pin_ in prev: ex(n_, lca, pin_)
    cc = class_cast(g, X + 300, -1100, 'AsActorClass%d' % i); link(lca['ReturnValue'], cc['Class']); ex(lca, cc)
    ga = g.call('/Script/Engine.GameplayStatics:GetAllActorsOfClass', 'AllOfClass%d' % i, X + 600, -1100)
    ga['OutActors'].t = ARR(ACTOR)
    link(cc['AsActor'], ga['ActorClass']); ex(cc, ga)
    lp = g.macro('ForEachLoop', ACTOR, X + 900, -1100, name='HeaterLoop%d' % i); link(ga['OutActors'], lp['Array']); ex(ga, lp, 'then', 'Exec')
    sc = set_cur(g, lp['Array Element'], X + 1100, -900, 'CurFromLoop%d' % i); ex(lp, sc, 'LoopBody')
    proc_entry_nodes.append(sc)
    prev = [(lp, 'Completed'), (cc, 'CastFailed')]

# PROCESS body (entry = 'then' of every set_cur)
X0 = 5800
cg = g.get('Cur', CUR_T, X0, 300, name='CurGet')
gc = g.call('/Script/Engine.Actor:GetComponentByClass', 'HeaterComp', X0, 450, ComponentClass=FH); link(cg['Cur'], gc['self'])
gc['ReturnValue'].t = OBJ(FH)
kg = g.get('Known', ARR(ACTOR), X0, 600, name='KnownChk')
kc = array_contains(g, ACTOR, X0 + 200, 600, 'AlreadyKnown'); link(kg['Known'], kc['TargetArray']); link(cg['Cur'], kc['ItemToFind'])
kn = g.call(KML + ':Not_PreBool', 'NotKnown', X0 + 400, 600); link(kc['ReturnValue'], kn['A'])
nh = g.call(KML + ':BooleanAND', 'NewHeater', X0 + 600, 500); link(is_valid(g, gc['ReturnValue'], X0 + 200, 450, 'CompValid'), nh['A']); link(kn['ReturnValue'], nh['B'])
bn = g.branch(X0 + 200, 0, 'BrNewHeater'); link(nh['ReturnValue'], bn['Condition'])
for n in proc_entry_nodes: ex(n, bn)
kg2 = g.get('Known', ARR(ACTOR), X0 + 400, 150, name='KnownAdd')
ak = g.arr('Array_Add', ACTOR, X0 + 500, 0, name='RememberHeater'); link(kg2['Known'], ak['TargetArray']); link(cg['Cur'], ak['NewItem']); ex(bn, ak)
fs = g.get('m_fuelSource', ENUM(PA + 'EFuelSource'), X0 + 600, 750, owner=FH, name='FuelSource'); link(gc['ReturnValue'], fs['self'])
notTemp = g.call(KML + ':NotEqual_ByteByte', 'NotCampfire', X0 + 800, 750, B='2'); link(fs['m_fuelSource'], notTemp['A'])
lsg = g.get('LoadScan', BOOL, X0 + 600, 900, name='LoadScanGet')
nl = g.call(KML + ':Not_PreBool', 'NotLoadScan', X0 + 800, 900); link(lsg['LoadScan'], nl['A'])
okc = g.call(KML + ':BooleanAND', 'ChangeThis', X0 + 1000, 800); link(notTemp['ReturnValue'], okc['A']); link(nl['ReturnValue'], okc['B'])
bc = g.branch(X0 + 800, 0, 'BrChangeThis'); link(okc['ReturnValue'], bc['Condition']); ex(ak, bc)
vg2 = g.get('View', VIEW_T, X0 + 1000, 250, name='ViewCtx')
sc_ = g.call(KSL + ':SetObjectPropertyByName', 'SetContext', X0 + 1100, 0, PropertyName='Context')
link(vg2['View'], sc_['Object']); link(cg['Cur'], sc_['Value']); ex(bc, sc_)
ch = g.call(VIEWC + ':CalcHudState', 'HudInfo', X0 + 1400, 0); link(vg2['View'], ch['self']); ex(sc_, ch)
hb = struct_node(g, 'Break', PA + 'FueledHeaterHudInfo', ['maxTempToEnable_playerUnits', 'allowReset'], X0 + 1400, 300, 'BreakHud')
link(ch['ReturnValue'], hb['FueledHeaterHudInfo'])
same = g.call(KML + ':EqualEqual_IntInt', 'AlreadyTarget', X0 + 1650, 400); link(hb['maxTempToEnable_playerUnits'], same['A']); link(tgt['ReturnValue'], same['B'])
skip = g.call(KML + ':BooleanOR', 'LeaveAlone', X0 + 1850, 300); link(hb['allowReset'], skip['A']); link(same['ReturnValue'], skip['B'])
bs = g.branch(X0 + 1700, 0, 'BrLeaveAlone'); link(skip['ReturnValue'], bs['Condition']); ex(ch, bs)
cga = g.cast(GA, False, X0 + 1950, 0, name='CurAsGridActor'); link(cg['Cur'], cga['Object']); ex(bs, cga, 'else')
cga['AsGrid Actor'].name = 'AsGridActor'
fp = g.get('liveFootprint', STRUCT(PA + 'GridFootprint'), X0 + 1950, 500, owner=GA, name='Footprint'); link(cga['AsGridActor'], fp['self'])
fb = struct_node(g, 'Break', PA + 'GridFootprint', ['rootPosition'], X0 + 2200, 500, 'BreakFootprint'); link(fp['liveFootprint'], fb['GridFootprint'])
mk = struct_node(g, 'Make', PA + 'HudAction', ['action', 'paramInt', 'paramGrid'], X0 + 2450, 300, 'MakeAction')
mk.set('action', 'setAutopauseLimit')
link(lim['ReturnValue'], mk['paramInt']); link(fb['rootPosition'], mk['paramGrid'])
ra = g.call(AWB + ':ReceiveHudAction', 'SendLimit', X0 + 2700, 0); link(vg2['View'], ra['self']); link(mk['HudAction'], ra['action'])
ex(cga, ra)
nm = g.call(KSL + ':GetDisplayName', 'HeaterName', X0 + 2700, 350); link(cg['Cur'], nm['Object'])
ts = g.call(KSTR + ':Conv_IntToString', 'TgtStr', X0 + 2700, 500); link(tgt['ReturnValue'], ts['inInt'])
msg = concat(g, X0 + 2950, 350, 'HeaterDefaults: ', nm['ReturnValue'], ' Turn on at -> ', ts['ReturnValue'], ' C')
l1 = log(g, X0 + 3000, 0, msg_pin=msg, name='LogSet'); ex(ra, l1)

# ---- after the class loops: nothing new and retries left -> try again in 1 s
same_n = g.call(KML + ':EqualEqual_IntInt', 'NothingNew', 5600, -1500); link(known_len(g, 5300, -1450, 'CountAfter'), same_n['A'])
kbg = g.get('KnownBefore', INT, 5300, -1350, name='KnownBeforeGet'); link(kbg['KnownBefore'], same_n['B'])
rg = g.get('Retries', INT, 5600, -1350, name='RetriesGet')
rok = g.call(KML + ':Greater_IntInt', 'RetriesLeft', 5800, -1350, B='0'); link(rg['Retries'], rok['A'])
again = g.call(KML + ':BooleanAND', 'TryAgain', 6000, -1450); link(same_n['ReturnValue'], again['A']); link(rok['ReturnValue'], again['B'])
ba = g.branch(5800, -1650, 'BrTryAgain'); link(again['ReturnValue'], ba['Condition'])
for n_, pin_ in prev: ex(n_, ba, pin_)
dec = g.call(KML + ':Subtract_IntInt', 'RetriesMinus1', 6100, -1500, B='1'); link(rg['Retries'], dec['A'])
sr2 = g.setv('Retries', INT, 6100, -1650, name='UseRetry'); link(dec['ReturnValue'], sr2['Retries']); ex(ba, sr2)
st2 = set_timer(g, 6400, -1650, 'RetryScanTimer'); ex(sr2, st2)
sr0 = g.setv('Retries', INT, 6100, -1800, value='0', name='StopRetries'); ex(ba, sr0, 'else')

open(OUT + '/BP_MapLoad.txt', 'w', encoding='utf-8').write(g.text())
print('wrote', OUT)
