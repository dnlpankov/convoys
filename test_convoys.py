import autograd
import datetime
import flaky
import matplotlib
import numpy
import pytest
import random
import scipy.special
import scipy.stats
matplotlib.use('Agg')  # Needed for matplotlib to run in Travis
import convoys
import convoys.gamma
import convoys.regression
import convoys.single


def sample_weibull(k, lambd):
    # scipy.stats is garbage for this
    # exp(-(x * lambda)^k) = y
    return (-numpy.log(random.random())) ** (1.0/k) / lambd


def generate_censored_data(N, E, C):
    B = numpy.array([c and e < n for n, e, c in zip(N, E, C)])
    T = numpy.array([e if b else n for e, b, n in zip(E, B, N)])
    return B, T


def test_gammainc(k=2.5, x=4.2, g_eps=1e-7):
    # Verify that function values are correct
    assert convoys.gamma.gammainc(k, x) == pytest.approx(scipy.special.gammainc(k, x))

    # Verify that it handles vectors
    assert convoys.gamma.gammainc(k, numpy.array([1, 2, 3])) == \
        pytest.approx(scipy.special.gammainc(k, numpy.array([1, 2, 3])))

    # Verify the derivative wrt k
    f_grad_k = autograd.grad(
        lambda k: convoys.gamma.gammainc(k, x))
    f_grad_k_numeric = (scipy.special.gammainc(k + g_eps, x) -
                        scipy.special.gammainc(k, x)) / g_eps
    assert f_grad_k(k) == pytest.approx(f_grad_k_numeric)

    # Verify the derivative wrt x
    f_grad_x = autograd.grad(
        lambda x: convoys.gamma.gammainc(k, x))
    f_grad_x_numeric = (scipy.special.gammainc(k, x + g_eps) -
                        scipy.special.gammainc(k, x)) / g_eps
    assert f_grad_x(x) == pytest.approx(f_grad_x_numeric)

    # Verify the derivative wrt x when x is a vector
    f_grad_x = autograd.grad(
        lambda x: autograd.numpy.sum(convoys.gamma.gammainc(1.0, x)))
    f_grad_x_correct = autograd.grad(
        lambda x: autograd.numpy.sum(1.0 - autograd.numpy.exp(-x)))
    xs = numpy.array([1., 2., 3.])
    assert f_grad_x(xs) == pytest.approx(f_grad_x_correct(xs))

    # Verify the derivative wrt k when x is a vector
    xs = numpy.array([1., 2., 3.])
    f_grad_k = autograd.grad(
        lambda k: autograd.numpy.sum(convoys.gamma.gammainc(k, xs)))
    assert f_grad_k(xs).shape == (3,)


@flaky.flaky
def test_exponential_regression_model(c=0.3, lambd=0.1, n=100000):
    X = numpy.ones((n, 1))
    C = scipy.stats.bernoulli.rvs(c, size=(n,))  # did it convert
    N = scipy.stats.uniform.rvs(scale=5./lambd, size=(n,))  # time now
    E = scipy.stats.expon.rvs(scale=1./lambd, size=(n,))  # time of event
    B, T = generate_censored_data(N, E, C)
    model = convoys.regression.Exponential()
    model.fit(X, B, T)
    assert model.cdf([1], float('inf')).shape == ()
    assert 0.90*c < model.cdf([1], float('inf')) < 1.20*c
    assert model.cdf([1], 0).shape == ()
    assert model.cdf([1], [0, 1, 2, 3]).shape == (4,)
    for t in [1, 3, 10]:
        d = 1 - numpy.exp(-lambd*t)
        assert 0.90*c*d < model.cdf([1], t) < 1.20*c*d

    # Check the confidence intervals
    assert model.cdf([1], float('inf'), ci=0.95).shape == (3,)
    assert model.cdf([1], [0, 1, 2, 3], ci=0.95).shape == (4, 3)
    y, y_lo, y_hi = model.cdf([1], float('inf'), ci=0.95)
    assert 0.90*c < y < 1.20*c

    # Check the random variates
    will_convert, convert_at = model.rvs([1], n_curves=1, n_samples=10000)
    assert 0.90*c < numpy.mean(will_convert) < 1.20*c
    convert_times = convert_at[will_convert]
    for t in [1, 3, 10]:
        d = 1 - numpy.exp(-lambd*t)
        assert 0.80*d < (convert_times < t).mean() < 1.30*d


@flaky.flaky
def test_weibull_regression_model(cs=[0.3, 0.5, 0.7], lambd=0.1, k=0.5, n=100000):
    X = numpy.array([[r % len(cs) == j for j in range(len(cs))] for r in range(n)])
    C = numpy.array([bool(random.random() < cs[r % len(cs)]) for r in range(n)])
    N = scipy.stats.uniform.rvs(scale=5./lambd, size=(n,))
    E = numpy.array([sample_weibull(k, lambd) for r in range(n)])
    B, T = generate_censored_data(N, E, C)

    model = convoys.regression.Weibull()
    model.fit(X, B, T)

    # Validate shape of results
    x = numpy.ones((len(cs),))
    assert model.cdf(x, float('inf')).shape == ()
    assert model.cdf(x, float('inf'), ci=0.95).shape == (3,)
    assert model.cdf(x, 1).shape == ()
    assert model.cdf(x, 1, ci=True).shape == (3,)
    assert model.cdf(x, [1, 2, 3, 4]).shape == (4,)
    assert model.cdf(x, [1, 2, 3, 4], ci=True).shape == (4, 3)

    # Check results
    for r, c in enumerate(cs):
        x = [int(r == j) for j in range(len(cs))]
        assert 0.90 * c < model.cdf(x, float('inf')) < 1.20 * c
        expected_time = 1./lambd * scipy.special.gamma(1 + 1/k)


@flaky.flaky
def test_gamma_regression_model(c=0.3, lambd=0.1, k=3.0, n=100000):
    # TODO: this one seems very sensitive to large values for N (i.e. less censoring)
    X = numpy.ones((n, 1))
    C = scipy.stats.bernoulli.rvs(c, size=(n,))
    N = scipy.stats.uniform.rvs(scale=20./lambd, size=(n,))
    E = scipy.stats.gamma.rvs(a=k, scale=1.0/lambd, size=(n,))
    B, T = generate_censored_data(N, E, C)

    model = convoys.regression.Gamma()
    model.fit(X, B, T)
    assert 0.90*c < model.cdf([1], float('inf')) < 1.20*c
    assert 0.90*k < numpy.mean(model.params['k']) < 1.10*k


@flaky.flaky
def test_nonparametric_model(c=0.3, lambd=0.1, k=0.5, n=10000):
    C = scipy.stats.bernoulli.rvs(c, size=(n,))
    N = scipy.stats.uniform.rvs(scale=30./lambd, size=(n,))
    E = numpy.array([sample_weibull(k, lambd) for r in range(n)])
    B, T = generate_censored_data(N, E, C)

    m = convoys.single.Nonparametric()
    m.fit(B, T)

    assert 0.90*c < m.cdf(float('inf')) < 1.10*c

    # Check shapes of results
    assert m.cdf(float('inf')).shape == ()
    assert m.cdf(float('inf'), ci=0.95).shape == (3,)
    assert m.cdf(1).shape == ()
    assert m.cdf([1, 2, 3, 4]).shape == (4,)
    assert m.cdf(1, ci=0.95).shape == (3,)
    assert m.cdf([1, 2, 3, 4], ci=0.95).shape == (4, 3)


def _test_plot_cohorts(cs=[0.3, 0.5, 0.7], k=0.5, lambd=0.1, n=10000, model='weibull', extra_model=None):
    C = numpy.array([bool(random.random() < cs[r % len(cs)]) for r in range(n)])
    N = scipy.stats.expon.rvs(scale=10./lambd, size=(n,))
    E = numpy.array([sample_weibull(k, lambd) for r in range(n)])
    B, T = generate_censored_data(N, E, C)
    data = []
    x2t = lambda x: datetime.datetime(2000, 1, 1) + datetime.timedelta(days=x)
    for i, (b, t, n) in enumerate(zip(B, T, N)):
        data.append(('Group %d' % (i % len(cs)),  # group name
                     x2t(0),  # created at
                     x2t(t) if b else None,  # converted at
                     x2t(n)))  # now

    matplotlib.pyplot.clf()
    _, result = convoys.plot_cohorts(data, model=model, extra_model=extra_model)
    matplotlib.pyplot.savefig('%s-%s.png' % (model, extra_model) if extra_model is not None else '%s.png' % model)
    group, y, y_lo, y_hi = result[0]
    c = cs[0]
    assert group == 'Group 0'
    if model != 'kaplan-meier':
        assert 0.90*c < y < 1.10 * c


@flaky.flaky
def test_plot_cohorts_kaplan_meier():
    _test_plot_cohorts(model='kaplan-meier')


@flaky.flaky
def test_plot_cohorts_weibull():
    _test_plot_cohorts(model='weibull')


@flaky.flaky
def test_plot_cohorts_nonparametric():
    _test_plot_cohorts(model='nonparametric')


@flaky.flaky
def test_plot_cohorts_two_models():
    _test_plot_cohorts(model='kaplan-meier', extra_model='nonparametric')
