import torch

from scar.backends import exact_reuse, pure
from scar.ir import StorageVersionRegistry, default_registry, mark_storage_write, storage_version
from scar.validate import compare


def test_exact_reuse_hits_and_copies_result():
    @pure
    def f(x):
        return x.square()

    wrapped = exact_reuse(f)
    x = torch.arange(4.0)
    with torch.no_grad():
        a, b = wrapped(x), wrapped(x)
    assert wrapped.misses == 1
    assert wrapped.hits == 1
    assert compare(a, b).passed
    b[0] = 999
    assert a[0] != 999


def test_cache_hit_preserves_inference_tensor_status():
    wrapped = exact_reuse(pure(lambda x: x.square()))
    x = torch.ones(4)
    with torch.inference_mode():
        first, second = wrapped(x), wrapped(x)
    assert first.is_inference() and second.is_inference()
    assert wrapped.hits == 1


def test_grad_mode_is_not_cached():
    calls = {"n": 0}

    def f(x):
        calls["n"] += 1
        return x * 2

    wrapped = exact_reuse(f)
    x = torch.ones(2, requires_grad=True)
    wrapped(x); wrapped(x)
    assert calls["n"] == 2


def test_unproven_callable_uses_noop_fallback():
    calls = {"n": 0}

    def stateful(x):
        calls["n"] += 1
        return x + calls["n"]

    wrapped = exact_reuse(stateful)
    with torch.inference_mode():
        first, second = wrapped(torch.ones(2)), wrapped(torch.ones(2))
    assert calls["n"] == 2
    assert not torch.equal(first, second)
    assert wrapped.hits == 0


def test_scar_storage_epoch_invalidates_after_observed_write():
    registry = StorageVersionRegistry()
    x = torch.ones(2)
    first = registry.token(x)
    registry.mark_write(x)
    assert registry.token(x) != first


def test_default_registry_is_the_backend_invalidation_source():
    x = torch.ones(2)
    before = storage_version(x)
    mark_storage_write(x)
    assert storage_version(x) != before
    assert default_registry() is default_registry()


def test_exact_reuse_does_not_merge_distinct_views_of_one_storage():
    @pure
    def f(x):
        return x.sum()

    wrapped = exact_reuse(f)
    base = torch.arange(8.0)
    with torch.inference_mode():
        left = wrapped(base[:4])
        right = wrapped(base[4:])
        left_again = wrapped(base[:4])
    assert wrapped.misses == 2
    assert float(left) == 6.0 and float(right) == 22.0
    assert float(left_again) == 6.0
    assert wrapped.hits == 1


def test_inference_tensor_inplace_write_invalidates_without_observer():
    wrapped = exact_reuse(pure(lambda x: x.square()))
    with torch.inference_mode():
        x = torch.ones(4)
        before = wrapped(x)
        x.add_(1)
        after = wrapped(x)
        again = wrapped(x)
    assert torch.equal(before, torch.ones(4))
    assert torch.equal(after, torch.full((4,), 4.0))
    assert torch.equal(after, again) and wrapped.hits == 1


def test_numpy_alias_write_invalidates_without_manual_mark():
    import numpy as np

    array = np.ones(4, dtype=np.float32)
    x = torch.from_numpy(array)
    wrapped = exact_reuse(pure(lambda x: x.square()))
    with torch.inference_mode():
        wrapped(x)
        array[:] = 3
        after = wrapped(x)
    assert torch.equal(after, torch.full((4,), 9.0))
    assert wrapped.hits == 0


def test_guard_distinguishes_signed_zero():
    wrapped = exact_reuse(pure(lambda x: torch.reciprocal(x)))
    x = torch.tensor([0.0])
    with torch.inference_mode():
        first = wrapped(x)
        x.mul_(-1)
        second = wrapped(x)
    assert first.item() == float("inf") and second.item() == float("-inf")
    assert wrapped.hits == 0


def test_module_parameters_and_buffers_are_guarded():
    class Affine(torch.nn.Module):
        scar_pure = True

        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.ones(1))
            self.register_buffer("bias", torch.zeros(1))

        def forward(self, x):
            return x * self.weight + self.bias

    module = Affine()
    wrapped = exact_reuse(module)
    x = torch.ones(1)
    with torch.inference_mode():
        first = wrapped(x)
        module.weight.add_(2)
        second = wrapped(x)
        module.bias.add_(4)
        third = wrapped(x)
    assert [v.item() for v in (first, second, third)] == [1, 3, 7]
    assert wrapped.hits == 0


def test_random_callable_without_contract_preserves_rng_progression():
    def random_region(x):
        return x + torch.rand_like(x)

    wrapped = exact_reuse(random_region)
    x = torch.ones(4)
    torch.manual_seed(12)
    with torch.inference_mode():
        expected = [random_region(x), random_region(x)]
        expected_rng = torch.random.get_rng_state()
        torch.manual_seed(12)
        actual = [wrapped(x), wrapped(x)]
    assert all(torch.equal(a, b) for a, b in zip(actual, expected))
    assert torch.equal(torch.random.get_rng_state(), expected_rng)
    assert wrapped.hits == 0


def test_declared_pure_random_callable_is_invalidated_by_rng_guard():
    @pure
    def random_region(x):
        return x + torch.rand_like(x)

    wrapped = exact_reuse(random_region)
    x = torch.ones(4)
    torch.manual_seed(31)
    with torch.inference_mode():
        expected = [random_region(x), random_region(x)]
        expected_rng = torch.random.get_rng_state()
        torch.manual_seed(31)
        actual = [wrapped(x), wrapped(x)]
    assert all(torch.equal(a, b) for a, b in zip(actual, expected))
    assert torch.equal(torch.random.get_rng_state(), expected_rng)
    assert wrapped.hits == 0
    assert "RNG" in wrapped.last_fallback


def test_declared_pure_module_with_hidden_counter_is_not_cached():
    class Counter(torch.nn.Module):
        scar_pure = True

        def __init__(self):
            super().__init__()
            self.counter = 0

        def forward(self, x):
            self.counter += 1
            return x + self.counter

    module = Counter()
    wrapped = exact_reuse(module)
    x = torch.ones(1)
    with torch.inference_mode():
        first = wrapped(x)
        second = wrapped(x)
    assert [first.item(), second.item()] == [2.0, 3.0]
    assert module.counter == 2
    assert wrapped.hits == 0
    assert "module state" in wrapped.last_fallback


def test_declared_pure_callable_with_callback_argument_is_not_cached():
    @pure
    def apply(callback, value):
        return callback(value)

    def callback(value):
        return value + 1

    wrapped = exact_reuse(apply)
    with torch.inference_mode():
        first = wrapped(callback, torch.ones(1))
        second = wrapped(callback, torch.ones(1))
    assert first.item() == 2 and second.item() == 2
    assert wrapped.hits == 0
    assert "input guard" in wrapped.last_fallback


def test_alias_return_preserves_identity_via_fallback():
    wrapped = exact_reuse(pure(lambda x: x))
    x = torch.ones(2)
    with torch.inference_mode():
        assert wrapped(x) is x
        assert wrapped(x) is x
    assert wrapped.hits == 0


def test_gradient_input_in_kwargs_uses_fallback():
    wrapped = exact_reuse(pure(lambda *, values: values[0].square()))
    x = torch.ones(2, requires_grad=True)
    with torch.no_grad():
        wrapped(values=[x])
        wrapped(values=[x])
    assert wrapped.hits == 0


def test_cache_retained_tensor_bytes_are_bounded():
    wrapped = exact_reuse(pure(lambda x: x.square()), max_bytes=8)
    x = torch.ones(4)
    with torch.inference_mode():
        wrapped(x)
        wrapped(x)
    assert wrapped.retained_bytes == 0 and not wrapped.cache
    assert wrapped.last_fallback == "entry exceeds cache byte budget"
