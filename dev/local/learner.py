#AUTOGENERATED! DO NOT EDIT! File to edit: dev/13_learner.ipynb (unless otherwise specified).

__all__ = ['CancelFitException', 'CancelEpochException', 'CancelTrainException', 'CancelValidException',
           'CancelBatchException', 'class2attr', 'Callback', 'TrainEvalCallback', 'GatherPredsCallback', 'event',
           'replacing_yield', 'mk_metric', 'Learner', 'VerboseCallback', 'Metric', 'AvgMetric', 'AvgLoss',
           'AvgSmoothLoss', 'Recorder']

#Cell
from .torch_basics import *
from .test import *
from .layers import *
from .data.all import *
from .notebook.showdoc import *
from .optimizer import *

#Cell
def class2attr(self, cls_name):
    return camel2snake(re.sub(rf'{cls_name}$', '', self.__class__.__name__) or cls_name.lower())

#Cell
@docs
class Callback():
    "Basic class handling tweaks of the training loop by changing a `Learner` in various events"
    def __call__(self, event_name): getattr(self, event_name, noop)()
    def __repr__(self): return self.__class__.__name__
    def __getattr__(self, k):
        if k=='learn': raise AttributeError
        if not hasattr(self,'learn'): raise AttributeError
        return getattr(self.learn, k)

    @property
    def name(self):
        "Name of the `Callback`, camel-cased and with '*Callback*' removed"
        return class2attr(self, 'Callback')

    _docs=dict(__call__="Call `self.{event_name}` if it's defined",
               __getattr__="Passthrough to get the attributes of `self.learn`")

#Cell
class TrainEvalCallback(Callback):
    "`Callback` that tracks the number of iterations done and properly sets training/eval mode"
    def begin_fit(self):
        "Set the iter and epoch counters to 0, put the model and the right device"
        self.learn.train_iter,self.learn.pct_train = 0,0.
        self.model.to(self.dbunch.device)

    def after_batch(self):
        "Update the iter counter (in training mode)"
        if not self.training: return
        self.learn.pct_train += 1./(self.n_iter*self.n_epoch)
        self.learn.train_iter   += 1

    def begin_train(self):
        "Set the model in training mode"
        self.learn.pct_train=self.epoch/self.n_epoch
        self.model.train()
        self.learn.training=True

    def begin_validate(self):
        "Set the model in validation mode"
        self.model.eval()
        self.learn.training=False

#Cell
class GatherPredsCallback(Callback):
    "`Callback` that saves the predictions and targets, optionally `with_loss`"
    def __init__(self, with_loss=False): self.with_loss = with_loss

    def begin_validate(self):
        "Initialize containers"
        self.preds,self.targets = [],[]
        if self.with_loss: self.losses = []

    def after_batch(self):
        "Save predictions, targets and potentially losses"
        self.preds.append(to_detach(self.pred))
        self.targets.append(to_detach(self.yb))
        if self.with_loss: self.losses.append(to_detach(self.loss))

#Cell
_ex_docs = dict(
    CancelFitException="Skip the rest of this batch and go to `after_batch`",
    CancelEpochException="Skip the rest of the training part of the epoch and go to `after_train`",
    CancelTrainException="Skip the rest of the validation part of the epoch and go to `after_validate`",
    CancelValidException="Skip the rest of this epoch and go to `after_epoch`",
    CancelBatchException="Interrupts training and go to `after_fit`")

for c,d in _ex_docs.items(): mk_class(c,sup=Exception,doc=d)

#Cell
_events = 'begin_fit begin_epoch begin_train begin_batch after_pred after_loss \
    after_backward after_step after_cancel_batch after_batch after_cancel_train \
    after_train begin_validate after_cancel_validate after_validate after_cancel_epoch \
    after_epoch after_cancel_fit after_fit'.split()

mk_class('event', **{o:o for o in _events},
         doc="All possible events as attributes to get tab-completion and typo-proofing")

_before_inference = [event.begin_fit, event.begin_epoch, event.begin_validate]
_after_inference  = [event.after_validate, event.after_epoch, event.after_fit]

#Cell
defaults.lr = slice(3e-3)
defaults.wd = 1e-2
defaults.callbacks = [TrainEvalCallback]

#Cell
def replacing_yield(o, attr, val):
    "Context manager to temporarily replace an attribute"
    old = getattr(o,attr)
    try:     yield setattr(o,attr,val)
    finally: setattr(o,attr,old)

#Cell
def mk_metric(m):
    "Convert `m` to an `AvgMetric`, unless it's already a `Metric`"
    return m if isinstance(m, Metric) else AvgMetric(m)

#Cell
class Learner():
    def __init__(self, dbunch, model, loss_func=None, opt_func=SGD, lr=defaults.lr, splitter=trainable_params, cbs=None,
                 cb_funcs=None, metrics=None, path=None, model_dir='models', wd_bn_bias=False, train_bn=True):
        store_attr(self, "dbunch,model,opt_func,lr,splitter,model_dir,wd_bn_bias,train_bn")
        self.training,self.logger,self.opt,self.cbs = False,print,None,L()
        #TODO: infer loss_func from data
        self.loss_func = CrossEntropyLossFlat() if loss_func is None else loss_func
        self.path = path if path is not None else getattr(dbunch, 'path', Path('.'))
        self.metrics = L(metrics).map(mk_metric)
        self.add_cbs(cbf() for cbf in L(defaults.callbacks)+L(cb_funcs))
        self.add_cbs(cbs)

    def add_cbs(self, cbs): L(cbs).map(self.add_cb)
    def remove_cbs(self, cbs): L(cbs).map(self.remove_cb)
    def add_cb(self, cb):
        old = getattr(self, cb.name, None)
        assert not old or isinstance(old, type(cb)), f"self.{cb.name} already registered"
        cb.learn = self
        setattr(self, cb.name, cb)
        self.cbs.append(cb)

    def remove_cb(self, cb):
        cb.learn = None
        if hasattr(self, cb.name): delattr(self, cb.name)
        if cb in self.cbs: self.cbs.remove(cb)

    @contextmanager
    def added_cbs(self, cbs):
        self.add_cbs(cbs)
        yield
        self.remove_cbs(cbs)

    def __call__(self, event_name): L(event_name).map(self._call_one)
    def _call_one(self, event_name):
        assert hasattr(event, event_name)
        [cb(event_name) for cb in sort_by_run(self.cbs)]

    def _bn_bias_state(self, with_bias): return bn_bias_params(self.model, with_bias).map(self.opt.state)
    def create_opt(self):
        self.opt = self.opt_func(self.splitter(self.model), lr=self.lr)
        if not self.wd_bn_bias:
            for p in self._bn_bias_state(True ): p['do_wd'] = False
        if self.train_bn:
            for p in self._bn_bias_state(False): p['force_train'] = True

    def all_batches(self):
        self.n_iter = len(self.dl)
        L(self.dl).enumerate().starmap(self.one_batch)

    def one_batch(self, i, b):
        try:
            self.iter,(self.xb,self.yb) = i,b;              self('begin_batch')
            self.pred = self.model(self.xb);                self('after_pred')
            self.loss = self.loss_func(self.pred, self.yb); self('after_loss')
            if not self.training: return
            self.loss.backward();                           self('after_backward')
            self.opt.step();                                self('after_step')
            self.opt.zero_grad()
        except CancelBatchException:                        self('after_cancel_batch')
        finally:                                            self('after_batch')

    def _do_begin_fit(self, n_epoch):
        self.n_epoch,self.loss = n_epoch,tensor(0.);        self('begin_fit')

    def _do_epoch_train(self):
        try:
            self.dl = self.dbunch.train_dl;                 self('begin_train')
            self.all_batches()
        except CancelTrainException:                        self('after_cancel_train')
        finally:                                            self('after_train')

    def _do_epoch_validate(self):
        try:
            self.dl = self.dbunch.valid_dl;                 self('begin_validate')
            with torch.no_grad(): self.all_batches()
        except CancelValidException:                        self('after_cancel_validate')
        finally:                                            self('after_validate')

    def fit(self, n_epoch, lr=None, wd=defaults.wd, cbs=None, reset_opt=False):
        with self.added_cbs(cbs):
            if reset_opt or not self.opt: self.create_opt()
            self.opt.set_hypers(wd=wd, lr=self.lr if lr is None else lr)

            try:
                self._do_begin_fit(n_epoch)
                for epoch in range(n_epoch):
                    try:
                        self.epoch=epoch;          self('begin_epoch')
                        self._do_epoch_train()
                        self._do_epoch_validate()
                    except CancelEpochException:   self('after_cancel_epoch')
                    finally:                       self('after_epoch')

            except CancelFitException:             self('after_cancel_fit')
            finally:                               self('after_fit')

    def validate(self, dl=None, cbs=None):
        self.dl = dl or self.dbunch.valid_dl
        with self.added_cbs(cbs), self.no_logging():
            self(_before_inference)
            self.all_batches()
            self(_after_inference)
        return self.recorder.values[-1]

    def get_preds(self, ds_idx=1, with_loss=False):
        self.dl = self.dbunch.dls[ds_idx]
        cb = GatherPredsCallback(with_loss=with_loss)
        with self.no_logging(), self.added_cbs(cb), self.loss_not_reduced():
            self(_before_inference)
            self.all_batches()
            self(_after_inference)
            if with_loss: return torch.cat(cb.preds),torch.cat(cb.targets),torch.cat(cb.losses)
            return torch.cat(cb.preds),torch.cat(cb.targets)

    @contextmanager
    def no_logging(self): return replacing_yield(self, 'logger', noop)

    @contextmanager
    def loss_not_reduced(self):
        if hasattr(self.loss_func, 'reduction'): return replacing_yield(self.loss_func, 'reduction', 'none')
        else: return replacing_yield(self, 'loss_func', partial(self.loss_func, reduction='none'))

    def save(self, file, with_opt=True):
        #TODO: if rank_distrib(): return # don't save if slave proc
        if not hasattr(self, 'opt'): with_opt=False
        state = get_model(self.model).state_dict()
        if with_opt: state = {'model': state, 'opt':self.opt.state_dict()}
        torch.save(state, join_path_file(file, self.path/self.model_dir, ext='.pth'))

    def load(self, file, with_opt=None, device=None, strict=True):
        if device is None: device = self.dbunch.device
        elif isinstance(device, int): device = torch.device('cuda', device)
        state = torch.load(join_path_file(file, self.path/self.model_dir, ext='.pth'))
        if set(state.keys()) == {'model', 'opt'}:
            model_state = state['model']
            get_model(self.model).load_state_dict(model_state, strict=strict)
            if ifnone(with_opt,True):
                if self.opt is None: self.create_opt()
                try: self.opt.load_state_dict(state['opt'])
                except:
                    if with_opt: warn("Could not load the optimizer state.")
        else:
            if with_opt: warn("Saved filed doesn't contain an optimizer state.")
            get_model(self.model).load_state_dict(state, strict=strict)
        return self

#Cell
add_docs(Learner, "Group together a `model`, some `dbunch` and a `loss_func` to handle training",
    add_cbs="Add `cbs` to the list of `Callback` and register `self` as their learner",
    add_cb="Add `cb` to the list of `Callback` and register `self` as their learner",
    remove_cbs="Remove `cbs` from the list of `Callback` and deregister `self` as their learner",
    remove_cb="Add `cb` from the list of `Callback` and deregister `self` as their learner",
    added_cbs="Context manage that temporarily adds `cbs`",
    create_opt="Create an optimizer with `lr`",
    one_batch="Train or evaluate `self.model` on batch `(xb,yb)`",
    all_batches="Train or evaluate `self.model` on all batches of `self.dl`",
    fit="Fit `self.model` for `n_epoch` using `cbs`. Optionally `reset_opt`.",
    validate="Validate on `dl` with potential new `cbs`.",
    get_preds="Get the predictions and targets on the `ds_idx`-th dbunchset, optionally `with_loss`",
    no_logging="Context manager to temporarily remove `logger`",
    loss_not_reduced="A context manager to evaluate `loss_func` with reduction set to none.",
    save="Save model and optimizer state (if `with_opt`) to `self.path/self.model_dir/file`",
    load="Load model and optimizer state (if `with_opt`) from `self.path/self.model_dir/file` using `device`"
)

#Cell
class VerboseCallback(Callback):
    "Callback that prints the name of each event called"
    def __call__(self, event_name):
        print(event_name)
        super().__call__(event_name)

#Cell
@docs
class Metric():
    "Blueprint for defining a metric"
    def reset(self): pass
    def accumulate(self, learn): pass
    @property
    def value(self): raise NotImplementedError

    @property
    def name(self): return class2attr(self, 'Metric')

    _docs = dict(
        reset="Reset inner state to prepare for new computation",
        name="Name of the `Metric`, camel-cased and with Metric removed",
        accumulate="Use `learn` to update the state with new results",
        value="The value of the metric")

#Cell
class AvgMetric(Metric):
    "Average the values of `func` taking into account potential different batch sizes"
    def __init__(self, func):  self.func = func
    def reset(self):           self.total,self.count = 0.,0
    def accumulate(self, learn):
        bs = find_bs(learn.yb)
        self.total += to_detach(self.func(learn.pred, learn.yb))*bs
        self.count += bs
    @property
    def value(self): return self.total/self.count if self.count != 0 else None
    @property
    def name(self):  return self.func.__name__

#Cell
class AvgLoss(Metric):
    "Average the losses taking into account potential different batch sizes"
    def reset(self):           self.total,self.count = 0.,0
    def accumulate(self, learn):
        bs = find_bs(learn.yb)
        self.total += to_detach(learn.loss)*bs
        self.count += bs
    @property
    def value(self): return self.total/self.count if self.count != 0 else None
    @property
    def name(self):  return "loss"

#Cell
class AvgSmoothLoss(Metric):
    "Smooth average of the losses (exponentially weighted with `beta`)"
    def __init__(self, beta=0.98): self.beta = beta
    def reset(self):               self.count,self.val = 0,tensor(0.)
    def accumulate(self, learn):
        self.count += 1
        self.val = torch.lerp(to_detach(learn.loss), self.val, self.beta)
    @property
    def value(self): return self.val/(1-self.beta**self.count)

#Cell
from fastprogress.fastprogress import format_time

def _maybe_item(t):
    t = t.value
    return t.item() if t.numel()==1 else t

#Cell
class Recorder(Callback):
    "Callback that registers statistics (lr, loss and metrics) during training"
    run_after = TrainEvalCallback

    def __init__(self, add_time=True, train_metrics=False, beta=0.98):
        self.add_time,self.train_metrics = add_time,train_metrics
        self.loss,self.smooth_loss = AvgLoss(),AvgSmoothLoss(beta=beta)

    def begin_fit(self):
        "Prepare state for training"
        self.lrs,self.losses,self.values = [],[],[]
        names = self._valid_mets.attrgot('name')
        if self.train_metrics: names = names.map('train_{}') + names.map('valid_{}')
        else:                  names = L('train_loss', 'valid_loss') + names[1:]
        if self.add_time: names.append('time')
        self.metric_names = 'epoch'+names
        self.smooth_loss.reset()

    def after_batch(self):
        "Update all metrics and records lr and smooth loss in training"
        mets = L(self.smooth_loss) + (self._train_mets if self.training else self._valid_mets)
        for met in mets: met.accumulate(self.learn)
        if not self.training: return
        self.lrs.append(self.opt.hypers[-1]['lr'])
        self.losses.append(self.smooth_loss.value)
        self.learn.smooth_loss = self.smooth_loss.value

    def begin_epoch(self):
        "Set timer if `self.add_time=True`"
        self.cancel_train,self.cancel_valid = False,False
        if self.add_time: self.start_epoch = time.time()
        self.log = L(getattr(self, 'epoch', 0))

    def begin_train   (self): self._train_mets.map(Self.reset())
    def begin_validate(self): self._valid_mets.map(Self.reset())
    def after_train   (self): self.log += self._train_mets.map(_maybe_item)
    def after_validate(self): self.log += self._valid_mets.map(_maybe_item)
    def after_cancel_train(self):    self.cancel_train = True
    def after_cancel_validate(self): self.cancel_valid = True

    def after_epoch(self):
        "Store and log the loss/metric values"
        self.values.append(self.log[1:].copy())
        if self.add_time: self.log.append(format_time(time.time() - self.start_epoch))
        self.logger(self.log)

    @property
    def _train_mets(self):
        if getattr(self, 'cancel_train', False): return L()
        return L(self.loss) + (self.metrics if self.train_metrics else L())

    @property
    def _valid_mets(self):
        if getattr(self, 'cancel_valid', False): return L()
        return L(self.loss) + self.metrics

    def plot_loss(self): plt.plot(self.losses)

#Cell
add_docs(Recorder,
         begin_train = "Reset loss and metrics state",
         after_train = "Log loss and metric values on the training set (if `self.training_metrics=True`)",
         begin_validate = "Reset loss and metrics state",
         after_validate = "Log loss and metric values on the validation set",
         after_cancel_train = "Ignore training metrics for this epoch",
         after_cancel_validate = "Ignore validation metrics for this epoch",
         plot_loss = "Plot the losses")

defaults.callbacks = [TrainEvalCallback, Recorder]

#Cell
@patch
def freeze_to(self:Learner, n):
    if self.opt is None: self.create_opt()
    self.opt.freeze_to(n)

@patch
def freeze(self:Learner): self.freeze_to(-1)

@patch
def unfreeze(self:Learner): self.freeze_to(0)

add_docs(Learner,
         freeze_to="Freeze parameter groups up to `n`",
         freeze="Freeze up to last parameter group",
         unfreeze="Unfreeze the entire model")