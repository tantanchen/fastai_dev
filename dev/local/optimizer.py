#AUTOGENERATED! DO NOT EDIT! File to edit: dev/12_optimizer.ipynb (unless otherwise specified).

__all__ = ['Optimizer', 'sgd_step', 'weight_decay', 'l2_reg', 'average_grad', 'average_sqr_grad', 'momentum_step',
           'SGD', 'rms_prop_step', 'RMSProp', 'step_stat', 'adam_step', 'Adam', 'larc_layer_lr', 'larc_step', 'Larc',
           'lamb_step', 'Lamb', 'detuplify_pg', 'set_item_pg', 'pytorch_hp_map', 'OptimWrapper']

#Cell
from .torch_basics import *
from .test import *

#Cell
class _BaseOptimizer():
    "Common functionality between `Optimizer` and `OptimWrapper`"

    def _set_require_grad(self, pg, rg):
        for p in pg: p.requires_grad_(rg or self.state[p].get('force_train', False))

    def freeze_to(self, n):
        self.frozen_idx = n if n >= 0 else len(self.param_groups) + n
        if self.frozen_idx >= len(self.param_groups):
            warn(f"Trying to freeze {self.frozen_idx} parameter groups when there are only {len(self.param_groups)}, the whole model is frozen.")
        for pg in self.param_groups[:n]: self._set_require_grad(pg, False)
        for pg in self.param_groups[n:]: self._set_require_grad(pg, True)

    def freeze(self):
        assert(len(self.param_groups)>1)
        self.freeze_to(-1)

    def unfreeze(self): self.freeze_to(0)
    def set_hypers(self, **kwargs): L(kwargs.items()).starmap(self.set_hyper)

    def _set_hyper(self, k, v):
        for v_,h in zip(v, self.hypers): h[k] = v_

    def set_hyper(self, k, v):
        if isinstance(v, slice):
            if v.start: v = even_mults(v.start, v.stop, len(self.param_groups))
            else: v = [v.stop/10]*(len(self.param_groups)-1) + [v.stop]
        v = L(v, use_list=None)
        if len(v)==1: v = v*len(self.param_groups)
        assert len(v) == len(self.hypers), f"Trying to set {len(v)} values for {k} but there are {len(self.param_groups)} parameter groups."
        self._set_hyper(k, v)

#Cell
class Optimizer(_BaseOptimizer):
    "Base optimizer class for the fastai library, updating `params` with `steppers`"
    _keep_on_clear = ['force_train', 'do_wd']
    def __init__(self, params, steppers, stats=None, train_bn=True, **defaults):
        steppers,params = L(steppers),L(params)
        self.stats,self.state,self.train_bn = L(stats),defaultdict(dict),train_bn
        defaults = merge(*self.stats.attrgot('defaults'), *steppers.attrgot('defaults'), defaults)
        self.param_groups = L(L(p) for p in params) if isinstance(params[0], (L,list)) else L([params])
        self.step_func = compose(*steppers)
        self.hypers = L({} for _ in range_of(self.param_groups))
        self.set_hypers(**defaults)
        self.frozen_idx = 0

    def _grad_params(self):
        "Helper function to loop over param groups then params that have a grad"
        return [(p,hyper) for pg,hyper in zip(self.param_groups,self.hypers)
            for p in pg if p.grad is not None]

    def zero_grad(self):
        for p,hyper in self._grad_params():
            p.grad.detach_()
            p.grad.zero_()

    def step(self):
        for p,hyper in self._grad_params():
            state = self.state[p]
            for stat in self.stats: state = stat(state, p, **hyper)
            self.step_func(p, **{**state, **hyper})
            self.state[p] = state

    def clear_state(self):
        for pg in self.param_groups:
            for p in pg: self.state[p] = {k: self.state[p][k] for k in self._keep_on_clear if k in self.state[p]}

    def state_dict(self):
        state = [self.state[p] for pg in self.param_groups for p in pg]
        return {'state': state, 'hypers': self.hypers}

    def load_state_dict(self, sd):
        assert len(sd["hypers"]) == len(self.param_groups)
        assert len(sd["state"])  == sum([len(pg) for pg in self.param_groups])
        self.hypers = sd['hypers']
        self.state = {p: s for p,s in zip([p for pg in self.param_groups for p in pg], sd['state'])}

#Cell
def sgd_step(p, lr, **kwargs):
    p.data.add_(-lr, p.grad.data)
    return p

#Cell
def weight_decay(p, lr, wd, do_wd=True, **kwargs):
    "Weight decay as decaying `p` with `lr*wd`"
    if do_wd: p.data.mul_(1 - lr*wd)
    return p
weight_decay.defaults = dict(wd=0.)

#Cell
def l2_reg(p, lr, wd, do_wd=True, **kwargs):
    "L2 regularization as adding `wd*p` to `p.grad`"
    if do_wd: p.grad.data.add_(wd, p.data)
    return p
l2_reg.defaults = dict(wd=0.)

#Cell
def average_grad(state, p, mom, dampening=False, **kwargs):
    "Keeps track of the avg grads of `p` in `state` with `mom`."
    if 'grad_avg' not in state: state['grad_avg'] = torch.zeros_like(p.grad.data)
    damp = 1-mom if dampening else 1.
    state['grad_avg'].mul_(mom).add_(damp, p.grad.data)
    return state

average_grad.defaults = dict(mom=0.9)

#Cell
def average_sqr_grad(state, p, sqr_mom, dampening=True, **kwargs):
    if 'sqr_avg' not in state: state['sqr_avg'] = torch.zeros_like(p.grad.data)
    damp = 1-sqr_mom if dampening else 1.
    state['sqr_avg'].mul_(sqr_mom).addcmul_(damp, p.grad.data, p.grad.data)
    return state

average_sqr_grad.defaults = dict(sqr_mom=0.99)

#Cell
def momentum_step(p, lr, grad_avg, **kwargs):
    "Step for SGD with momentum with `lr`"
    p.data.add_(-lr, grad_avg)
    return p

#Cell
def SGD(params, lr, mom=0., wd=0., true_wd=True):
    "A `Optimizer` for SGD with `lr` and `mom` and `params`"
    steppers = [] if wd==0. else [weight_decay] if true_wd else [l2_reg]
    steppers.append(sgd_step if mom==0 else momentum_step)
    if mom == 0.: return Optimizer(params, steppers, lr=lr, wd=wd)
    else: return Optimizer(params, steppers, stats=average_grad, lr=lr, mom=mom, wd=wd)

#Cell
def rms_prop_step(p, lr, sqr_avg, eps, grad_avg=None, **kwargs):
    "Step for SGD with momentum with `lr`"
    denom = sqr_avg.sqrt().add_(eps)
    p.data.addcdiv_(-lr, (grad_avg if grad_avg is not None else p.grad), denom)
    return p

rms_prop_step.defaults = dict(eps=1e-8)

#Cell
def RMSProp(params, lr, sqr_mom=0.99, mom=0., wd=0., true_wd=True):
    "A `Optimizer` for RMSProp with `lr`, `sqr_mom`, `mom` and `params`"
    steppers = [] if wd==0. else [weight_decay] if true_wd else [l2_reg]
    steppers.append(rms_prop_step)
    stats = [average_sqr_grad] if mom==0. else [average_grad, average_sqr_grad]
    return Optimizer(params, steppers, stats=stats, lr=lr, mom=mom, sqr_mom=sqr_mom, wd=wd)

#Cell
def step_stat(state, p, **kwargs):
    "Register the number of steps done in `state` for `p`"
    if 'step' not in state: state['step'] = 0
    state['step'] += 1
    return state

#Cell
def _debias(mom, damp, step): return damp * (1 - mom**step) / (1-mom)

def adam_step(p, lr, mom, step, sqr_mom, grad_avg, sqr_avg, eps, **kwargs):
    "Step for Adam with `lr` on `p`"
    debias1 = _debias(mom,     1-mom,     step)
    debias2 = _debias(sqr_mom, 1-sqr_mom, step)
    p.data.addcdiv_(-lr / debias1, grad_avg, (sqr_avg/debias2).sqrt() + eps)
    return p

adam_step._defaults = dict(eps=1e-5)

#Cell
def Adam(params, lr, mom=0.9, sqr_mom=0.99, eps=1e-5, wd=0., true_wd=True):
    "A `Optimizer` for Adam with `lr`, `mom`, `sqr_mom`, `eps` and `params`"
    steppers = [] if wd==0. else [weight_decay] if true_wd else [l2_reg]
    steppers.append(adam_step)
    stats = [partial(average_grad, dampening=True), average_sqr_grad, step_stat]
    return Optimizer(params, steppers, stats=stats, lr=lr, mom=mom, sqr_mom=sqr_mom, eps=eps, wd=wd)

#Cell
def larc_layer_lr(state, p, lr, trust_coeff, wd, eps, clip=True, **kwargs):
    "Computes the local lr before weight decay is applied"
    p_norm,g_norm = torch.norm(p.data),torch.norm(p.grad.data)
    local_lr = lr*trust_coeff * (p_norm) / (g_norm + p_norm * wd + eps)
    state['local_lr'] = min(lr, local_lr) if clip else local_lr
    return state
larc_layer_lr.defaults = dict(trust_coeff=0.02, wd=0., eps=1e-8)

#Cell
def larc_step(p, local_lr, grad_avg=None, **kwargs):
    "Step for LARC `local_lr` on `p`"
    p.data.add_(-local_lr, p.grad.data if grad_avg is None else grad_avg)
    return p

#Cell
def Larc(params, lr, mom=0.9, clip=True, trust_coeff=0.02, eps=1e-8, wd=0., true_wd=True):
    "A `Optimizer` for Adam with `lr`, `mom`, `sqr_mom`, `eps` and `params`"
    steppers = [] if wd==0. else [weight_decay] if true_wd else [l2_reg]
    steppers.append(larc_step)
    stats = [] if mom==0. else [average_grad]
    stats.append(partial(larc_layer_lr, clip=clip))
    return Optimizer(params, steppers, stats=stats, lr=lr, mom=mom, trust_coeff=trust_coeff, eps=eps, wd=wd)

#Cell
def lamb_step(p, lr, mom, step, sqr_mom, grad_avg, sqr_avg, eps, **kwargs):
    "Step for LAMB with `lr` on `p`"
    debias1 = _debias(mom,     1-mom,     step)
    debias2 = _debias(sqr_mom, 1-sqr_mom, step)
    r1 = p.data.pow(2).mean().sqrt()
    step = (grad_avg/debias1) / ((sqr_avg/debias2).sqrt()+eps)
    r2 = step.pow(2).mean().sqrt()
    q = 1 if r1 == 0 or r2 == 0 else min(r1/r2,10)
    p.data.add_(-lr * q, step)
    return p
lamb_step._defaults = dict(eps=1e-6, wd=0.)

#Cell
def Lamb(params, lr, mom=0.9, sqr_mom=0.99, eps=1e-5, wd=0., true_wd=True):
    "A `Optimizer` for Adam with `lr`, `mom`, `sqr_mom`, `eps` and `params`"
    steppers = [] if wd==0. else [weight_decay] if true_wd else [l2_reg]
    steppers.append(lamb_step)
    stats = [partial(average_grad, dampening=True), average_sqr_grad, step_stat]
    return Optimizer(params, steppers, stats=stats, lr=lr, mom=mom, sqr_mom=sqr_mom, eps=eps, wd=wd)

#Cell
def detuplify_pg(d):
    res = {}
    for k,v in d.items():
        if k == 'params': continue
        if is_listy(v): res.update(**{f'{k}_{i}': v_ for i,v_ in enumerate(v)})
        else: res[k] = v
    return res

#Cell
def set_item_pg(pg, k, v):
    if '_' not in k: pg[k] = v
    else:
        name,idx = k.split('_')
        pg[name] = tuple(v if i==int(idx) else pg[name][i] for i in range_of(pg[name]))
    return pg

#Cell
pytorch_hp_map = {'momentum': 'mom', 'weight_decay': 'wd', 'alpha': 'sqr_mom', 'betas_0': 'mom', 'betas_1': 'sqr_mom'}

#Cell
class OptimWrapper(_BaseOptimizer, GetAttr):
    _xtra=['zero_grad', 'step', 'state_dict', 'load_state_dict']
    def __init__(self, opt, hp_map=None):
        self.default = self.opt = opt
        if hp_map is None: hp_map = pytorch_hp_map
        self.fwd_map = {k: hp_map[k] if k in hp_map else k for k in detuplify_pg(opt.param_groups[0]).keys()}
        self.bwd_map = {v:k for k,v in self.fwd_map.items()}

    @property
    def param_groups(self): return [pg['params'] for pg in self.opt.param_groups]
    @param_groups.setter
    def param_groups(self, v):
        for pg,v_ in zip(self.opt.param_groups,v): pg['params'] = v_

    @property
    def hypers(self):
        return [{self.fwd_map[k]:v for k,v in detuplify_pg(pg).items() if k != 'params'} for pg in self.opt.param_groups]

    def _set_hyper(self, k, v):
        for pg,v_ in zip(self.opt.param_groups,v): pg = set_item_pg(pg, self.bwd_map[k], v_)

    def clear_state(self): self.opt.state = defaultdict(dict, {})