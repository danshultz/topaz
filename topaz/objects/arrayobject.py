import copy

from rpython.rlib.listsort import TimSort
from rpython.rlib.rerased import new_static_erasing_pair

from topaz.coerce import Coerce
from topaz.module import ClassDef, check_frozen
from topaz.modules.enumerable import Enumerable
from topaz.objects.objectobject import W_Object
from topaz.utils.packing.pack import RPacker
from topaz.objects.floatobject import W_FloatObject
from topaz.objects.intobject import W_FixnumObject

class RubySorter(TimSort):
    def __init__(self, space, list, listlength=None, sortblock=None):
        TimSort.__init__(self, list, listlength=listlength)
        self.space = space
        self.sortblock = sortblock

    def lt(self, a, b):
        if self.sortblock is None:
            w_cmp_res = self.space.send(a, self.space.newsymbol("<=>"), [b])
        else:
            w_cmp_res = self.space.invoke_block(self.sortblock, [a, b])
        if w_cmp_res is self.space.w_nil:
            raise self.space.error(
                self.space.w_ArgumentError,
                "comparison of %s with %s failed" % (self.space.getclass(a).name, self.space.getclass(b).name)
            )
        else:
            return self.space.int_w(w_cmp_res) < 0
            
class IntSorter(RubySorter):
    def lt(self, a, b):
        if self.sortblock is None:
            return a < b
        else:
            w_cmp_res = self.space.invoke_block(self.sortblock, 
                                               [self.space.newint(a),
                                                self.space.newint(b)])
            if w_cmp_res is self.space.w_nil:
                raise self.space.error(
                    self.space.w_ArgumentError,
                    "comparison of %s with %s failed" % (self.space.getclass(a).name, 
                                                         self.space.getclass(b).name)
                    )
            else:
                return self.space.int_w(w_cmp_res) < 0

class FloatSorter(RubySorter):
    def lt(self, a, b):
        if self.sortblock is None:
            return a < b
        else:
            w_cmp_res = self.space.invoke_block(self.sortblock, 
                                               [self.space.newfloat(a), 
                                                self.space.newfloat(b)])
            if w_cmp_res is self.space.w_nil:
                raise self.space.error(
                    self.space.w_ArgumentError,
                    "comparison of %s with %s failed" % (self.space.getclass(a).name, 
                                                         self.space.getclass(b).name)
                )
            else:
                return self.space.int_w(w_cmp_res) < 0
    
class ArrayStrategy(object):
    
    def __init__(self, space):
        pass
    
    def __deepcopy__(self, memo):
        memo[id(self)] = result = object.__new__(self.__class__)
        return result
    
class ArrayStrategyMixin(object):
    
    _mixin_ = True
        
    def length(self, a):
        return len(self.unerase(a.array_storage))
        
    def range_assign(self, space, a, start, end, w_obj):
        assert end >= 0
        w_converted = space.convert_type(w_obj, space.w_array, "to_ary", raise_error=False)
        if w_converted is space.w_nil:
            rep_w = [w_obj]
            self.verify_strategy(space, a, w_obj)
        else:
            rep_w = space.listview(w_converted)
            for each in rep_w:
                self.verify_strategy(space, a, each)
        delta = (end - start) - len(rep_w)
	# storage can be of different array type after strategy is verified -> decorator ? ifs?
	a.strategy.padd_assign(space, a, delta, start, end, rep_w)

    def padd_assign(self, space, a, delta, start, end, rep_w):
	storage = self.unerase(a.array_storage)
        if delta < 0:
            storage += [None] * -delta
            lim = start + len(rep_w)
            i = len(storage) - 1
            while i >= lim:
                storage[i] = storage[i + delta]
                i -= 1
        elif delta > 0:
            del storage[start:start + delta]
        storage[start:start + len(rep_w)] = [self.unwrap(space, r) for r in rep_w]
        
    def slice(self, space, a, start, end):
        return space.newarray(self.listview(space, a)[start:end])
        
    def slice_i(self, space, a, start, end, as_range, nil):
        if nil:
            return space.w_nil
        elif as_range:
            start = min(max(start, 0), self.length(a))
            end = min(max(end, 0), self.length(a))
            delta = (end - start)
            assert delta >= 0
            w_items = self.listview(space, a)[start:start + delta]
            del self.unerase(a.array_storage)[start:start + delta]
            return space.newarray(w_items)
        else:
            storage = self.unerase(a.array_storage)
            w_item = storage[start]
            del storage[start]
            return w_item
        
    def shift(self, space, a, n):
        if n < 0:
            raise space.error(space.w_ArgumentError, "negative array size")
        items_w = self.listview(space, a)[:n]
        del self.unerase(a.array_storage)[:n]
        return space.newarray(items_w)
        
    def clear(self, space, a):
        del self.unerase(a.array_storage)[:]
            
    def pop_n(self, space, a, num):
        pop_size = max(0, self.length(a) - num)
        res_w = self.listview(space, a)[pop_size:]
        del self.unerase(a.array_storage)[pop_size:]
        return space.newarray(res_w)
        
    def replace(self, space, a, other_w):
        for o in other_w:
            if not self.checktype(o):
                obj_strategy = space.fromcache(ObjectArrayStrategy)
                a.array_storage = obj_strategy.store(space, other_w)
		a.strategy = obj_strategy
                return
        a.array_store = self.store(space, other_w)            
        
    def verify_strategy(self, space, a, w_obj):
        if not self.checktype(w_obj):
            obj_strategy = space.fromcache(ObjectArrayStrategy)
            a.array_storage = obj_strategy.erase(self.listview(space, a))
	    a.strategy = obj_strategy
    
    def store(self, space, items_w):
	l = []
	for o in items_w:
	    assert self.checktype(o)
	    l.append(self.unwrap(space, o))
	return self.erase(l)
        
    def get_item(self, space, a, idx):
        return self.wrap(space, self.unerase(a.array_storage)[idx])
        
    def set_item(self, space, a, idx, w_obj):
        self.verify_strategy(space, a, w_obj)
        if self.checktype(w_obj):
            self.unerase(a.array_storage)[idx] = self.unwrap(space, w_obj)
        else:
	    obj_strategy = space.fromcache(ObjectArrayStrategy)
            obj_strategy.unerase(a.array_storage)[idx] = obj_strategy.unwrap(space, w_obj)
        
    def listview(self, space, a):
        return [self.wrap(space, o) for o in self.unerase(a.array_storage)]
        
    def extend(self, space, a, other_w):
        for o in other_w:
            if not self.checktype(o):
                obj_strategy = space.fromcache(ObjectArrayStrategy)
                a.array_storage = obj_strategy.erase(self.listview(space, a))
                obj_strategy.unerase(a.array_storage).extend(other_w)
		a.strategy = obj_strategy
                return
	l = []
	for o in other_w:
	    assert self.checktype(o)
	    l.append(self.unwrap(space, o))
        self.unerase(a.array_storage).extend(l)
        
    def append(self, space, a, w_obj):
        self.verify_strategy(space, a, w_obj)
        if self.checktype(w_obj):
            self.unerase(a.array_storage).append(self.unwrap(space, w_obj))
        else:
            obj_strategy = space.fromcache(ObjectArrayStrategy)
            obj_strategy.unerase(a.array_storage).append(obj_strategy.unwrap(space, w_obj))
        
    def pop(self, space, a, idx):
        storage = self.unerase(a.array_storage)
        if storage:
            return self.wrap(space, storage.pop(idx))
        else:
            return space.w_nil
            
    def insert(self, space, a, idx, w_obj):
        self.verify_strategy(space, a, w_obj)
        if self.checktype(w_obj):
            self.unerase(a.array_storage).insert(idx, self.unwrap(space, w_obj))
        else:
	    obj_strategy = space.fromcache(ObjectArrayStrategy)
            obj_strategy.unerase(a.array_storage).insert(idx, obj_strategy.unwrap(space, w_obj))
    
class ObjectArrayStrategy(ArrayStrategyMixin, ArrayStrategy):
    
    erase, unerase = new_static_erasing_pair("object")
    
    def verify_strategy(self, space, a, w_obj):
        pass 
        
    def wrap(self, space, w_obj):
        return w_obj
        
    def unwrap(self, space, w_obj):
        return w_obj
        
    def checktype(self, w_obj):
        return True
        
    def sort(self, space, a, block):
        RubySorter(space, self.unerase(a.array_storage), sortblock=block).sort()
    
class FloatArrayStrategy(ArrayStrategyMixin, ArrayStrategy):
    
    erase, unerase = new_static_erasing_pair("float")
    
    def wrap(self, space, f):
        return space.newfloat(f)
        
    def unwrap(self, space, w_f):
        return space.float_w(w_f)
        
    def checktype(self, w_obj):
        return isinstance(w_obj, W_FloatObject)
    
    def sort(self, space, a, block):
        FloatSorter(space, self.unerase(a.array_storage), sortblock=block).sort()
    
class FixnumArrayStrategy(ArrayStrategyMixin, ArrayStrategy):
    
    erase, unerase = new_static_erasing_pair("fixnum")
    
    def wrap(self, space, i):
	assert isinstance(i, int)
        return space.newint(i)
        
    def unwrap(self, space, w_i):
        return space.int_w(w_i)
        
    def checktype(self, w_obj):
        return isinstance(w_obj, W_FixnumObject)
            
    def sort(self, space, a, block):
        IntSorter(space, self.unerase(a.array_storage), sortblock=block).sort()

class W_ArrayObject(W_Object):
    classdef = ClassDef("Array", W_Object.classdef, filepath=__file__)
    classdef.include_module(Enumerable)

    def __init__(self, space, strategy, items_w):
        W_Object.__init__(self, space)
        self.strategy = strategy
        self.array_storage = self.strategy.store(space, items_w)

    def __deepcopy__(self, memo):
        obj = super(W_ArrayObject, self).__deepcopy__(memo)
        obj.strategy = copy.deepcopy(self.strategy, memo)
        obj.array_storage = copy.deepcopy(self.array_storage, memo)
        return obj

    def listview(self, space):
        return self.strategy.listview(space, self)
        
    def length(self):
        return self.strategy.length(self)

    @classdef.singleton_method("allocate")
    def singleton_method_allocate(self, space, args_w):
        return space.newarray([])

    @classdef.singleton_method("[]")
    def singleton_method_subscript(self, space, args_w):
        return space.newarray(args_w)

    @classdef.method("initialize_copy", other_w="array")
    @classdef.method("replace", other_w="array")
    @check_frozen()
    def method_replace(self, space, other_w):
        self.strategy.replace(space, self, other_w)
        return self

    @classdef.method("at")
    @classdef.method("[]")
    @classdef.method("slice")
    def subscript(self, space, w_idx, w_count=None):
        start, end, as_range, nil = space.subscript_access(self.length(), w_idx, w_count=w_count)
        if nil:
            return space.w_nil
        elif as_range:
            assert start >= 0
            assert end >= 0
            return self.strategy.slice(space, self, start, end)
        else:
            return self.strategy.get_item(space, self, start)

    @classdef.method("[]=")
    def method_subscript_assign(self, space, w_idx, w_count_or_obj, w_obj=None):
        w_count = None
        if w_obj:
            w_count = w_count_or_obj
        else:
            w_obj = w_count_or_obj
        start, end, as_range, nil = space.subscript_access(self.length(), w_idx, w_count=w_count)

        if w_count and end < start:
            raise space.error(space.w_IndexError,
                "negative length (%d)" % (end - start)
            )
        elif start < 0:
            raise space.error(space.w_IndexError,
                "index %d too small for array; minimum: %d" % (
                    start - self.length(),
                    -self.length()
                )
            )
        elif start >= self.length():
            self.strategy.extend(space, self, 
                                                [space.w_nil] * (start - self.length() + 1))
            self.strategy.set_item(space, self, start, w_obj)
        elif as_range:
            self.strategy.range_assign(space, self, start, end, w_obj)
        else:
            self.strategy.set_item(space, self, start, w_obj)
        return w_obj

    @classdef.method("slice!")
    @check_frozen()
    def method_slice_i(self, space, w_idx, w_count=None):
        start, end, as_range, nil = space.subscript_access(self.length(), w_idx, w_count=w_count)
        return self.strategy.slice_i(space, self, start, end, as_range, nil)

    @classdef.method("size")
    @classdef.method("length")
    def method_length(self, space):
        return space.newint(self.length())

    @classdef.method("empty?")
    def method_emptyp(self, space):
        return space.newbool(self.length() == 0)

    @classdef.method("+", other="array")
    def method_add(self, space, other):
        return space.newarray(self.listview(space) + other)

    @classdef.method("<<")
    @check_frozen()
    def method_lshift(self, space, w_obj):
        self.strategy.append(space, self, w_obj)
        return self

    @classdef.method("concat", other="array")
    @check_frozen()
    def method_concat(self, space, other):
        self.strategy.extend(space, self, other)
        return self

    @classdef.method("push")
    @check_frozen()
    def method_concat(self, space, args_w):
        self.strategy.extend(space, self, args_w)
        return self

    @classdef.method("shift")
    @check_frozen()
    def method_shift(self, space, w_n=None):
        if w_n is None:
            return self.strategy.pop(space, self, 0)
        n = space.int_w(space.convert_type(w_n, space.w_fixnum, "to_int"))
        return self.strategy.shift(space, self, n)

    @classdef.method("unshift")
    @check_frozen()
    def method_unshift(self, space, args_w):        
        for i in xrange(len(args_w) - 1, -1, -1):
            w_obj = args_w[i]
            self.strategy.insert(space, self, 0, w_obj)
        return self

    @classdef.method("join")
    def method_join(self, space, w_sep=None):
        if not self.listview(space):
            return space.newstr_fromstr("")
        if w_sep is None:
            separator = ""
        elif space.respond_to(w_sep, space.newsymbol("to_str")):
            separator = space.str_w(space.send(w_sep, space.newsymbol("to_str")))
        else:
            raise space.error(space.w_TypeError,
                "can't convert %s into String" % space.getclass(w_sep).name
            )
        return space.newstr_fromstr(separator.join([
            space.str_w(space.send(w_o, space.newsymbol("to_s")))
            for w_o in self.listview(space)
        ]))

    @classdef.singleton_method("try_convert")
    def method_try_convert(self, space, w_obj):
        if not space.is_kind_of(w_obj, space.w_array):
            w_obj = space.convert_type(w_obj, space.w_array, "to_ary", raise_error=False)
        return w_obj

    @classdef.method("pop")
    @check_frozen()
    def method_pop(self, space, w_num=None):
        if w_num is None:
            return self.strategy.pop(space, self, -1)
        else:
            num = space.int_w(space.convert_type(
                w_num, space.w_fixnum, "to_int"
            ))
            if num < 0:
                raise space.error(space.w_ArgumentError, "negative array size")
            else:
                return self.strategy.pop_n(space, self, num)

    @classdef.method("delete_at", idx="int")
    @check_frozen()
    def method_delete_at(self, space, idx):
        if idx < 0:
            idx += self.length()
        if idx < 0 or idx >= self.length():
            return space.w_nil
        else:
            return self.strategy.pop(space, self, idx)

    @classdef.method("last")
    def method_last(self, space, w_count=None):
        if w_count is not None:
            count = Coerce.int(space, w_count)
            if count < 0:
                raise space.error(space.w_ArgumentError, "negative array size")
            start = self.length() - count
            if start < 0:
                start = 0
            return space.newarray(self.listview(space)[start:])

        if self.length() == 0:
            return space.w_nil
        else:
            return self.listview(space)[self.length() - 1]

    @classdef.method("pack", template="str")
    def method_pack(self, space, template):
        result = RPacker(template, space.listview(self)).operate(space)
        return space.newstr_fromchars(result)

    @classdef.method("to_ary")
    def method_to_ary(self, space):
        return self

    @classdef.method("clear")
    @check_frozen()
    def method_clear(self, space):
        self.strategy.clear(space, self)
        return self

    @classdef.method("sort!")
    def method_sort(self, space, block):
        self.strategy.sort(space, self, block)
        return self
        
    @classdef.method("dup")
    def method_dup(self, space, block):
        # this needs to be here, as the Kernel>>dup 
        # aparrently can not sucessfully copy arrays
        # which are based on this new storage model
        return space.newarray(self.listview(space))
