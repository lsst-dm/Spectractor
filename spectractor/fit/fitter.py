from iminuit import Minuit
from scipy import optimize
from schwimmbad import MPIPool
import emcee
import time
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import sys
import os
import multiprocessing

from spectractor import parameters
from spectractor.config import set_logger
from spectractor.tools import formatting_numbers, compute_correlation_matrix, plot_correlation_matrix_simple
from spectractor.fit.statistics import Likelihood


class FitWorkspace:

    def __init__(self, file_name="", nwalkers=18, nsteps=1000, burnin=100, nbins=10,
                 verbose=0, plot=False, live_fit=False, truth=None):
        """Generic class to create a fit workspace with parameters, bounds and general fitting methods.

        Parameters
        ----------
        file_name: str, optional
            The generic file name to save results. If file_name=="", nothing is saved ond disk (default: "").
        nwalkers: int, optional
            Number of walkers for MCMC exploration (default: 18).
        nsteps: int, optional
            Number of steps for MCMC exploration (default: 1000).
        burnin: int, optional
            Number of burn-in steps for MCMC exploration (default: 100).
        nbins: int, optional
            Number of bins to make histograms after MCMC exploration (default: 10).
        verbose: int, optional
            Level of verbosity (default: 0).
        plot: bool, optional
            Level of plotting (default: False).
        live_fit: bool, optional, optional
            If True, model, data and residuals plots are made along the fitting procedure (default: False).
        truth: array_like, optional
            Array of true parameters (default: None).

        Examples
        --------
        >>> w = FitWorkspace()
        >>> w.ndim
        0
        """
        self.my_logger = set_logger(self.__class__.__name__)
        self.filename = file_name
        self.truth = truth
        self.verbose = verbose
        self.plot = plot
        self.live_fit = live_fit
        self.p = np.array([])
        self.cov = np.array([[]])
        self.rho = np.array([[]])
        self.data = None
        self.err = None
        self.data_cov = None
        self.data_invcov = None
        self.x = None
        self.outliers = []
        self.sigma_clip = 5
        self.model = None
        self.model_err = None
        self.model_noconv = None
        self.input_labels = []
        self.axis_names = []
        self.input_labels = []
        self.bounds = ((), ())
        self.fixed = []
        self.nwalkers = max(2 * self.ndim, nwalkers)
        self.nsteps = nsteps
        self.nbins = nbins
        self.burnin = burnin
        self.start = []
        self.likelihood = np.array([[]])
        self.gelmans = np.array([])
        self.chains = np.array([[]])
        self.lnprobs = np.array([[]])
        self.costs = np.array([[]])
        self.params_table = None
        self.flat_chains = np.array([[]])
        self.valid_chains = [False] * self.nwalkers
        self.global_average = None
        self.global_std = None
        self.title = ""
        self.use_grid = False
        if self.filename != "":
            if "." in self.filename:
                self.emcee_filename = os.path.splitext(self.filename)[0] + "_emcee.h5"
            else:
                self.my_logger.warning("\n\tFile name must have an extension.")
        else:
            self.emcee_filename = "emcee.h5"

    @property
    def ndim(self):
        """Number of parameters of the model.

        Returns
        -------
        ndim: int

        """
        return len(self.p)

    @property
    def not_outliers(self):
        """List of points that are not outliers rejected by a sigma-clipping method or other masking method.

        Returns
        -------
        not_outliers: list

        """
        if len(self.outliers) > 0:
            return [i for i in range(self.data.size) if i not in self.outliers]
        else:
            return list(np.arange(self.data.size))

    def set_start(self, percent=0.02, a_random=1e-5):
        """Set the random starting points for MCMC exploration.

        A set of parameters are drawn with a uniform distribution between +/- percent times the starting guess.
        For null guess parameters, starting points are drawn from a uniform distribution between +/- a_random.

        Parameters
        ----------
        percent: float, optional
            Percent of the guess parameters to set the uniform interval to draw random points (default: 0.02).
        a_random: float, optional
            Absolute value to set the +/- uniform interval to draw random points
            for null guess parameters (default: 1e-5).

        Returns
        -------
        start: np.array
            Array of starting points of shape (ndim, nwalkers).

        """
        self.start = np.array(
            [np.random.uniform(self.p[i] - percent * self.p[i], self.p[i] + percent * self.p[i], self.nwalkers)
             for i in range(self.ndim)]).T
        self.start[self.start == 0] = a_random * np.random.uniform(-1, 1)
        return self.start

    def load_chains(self):
        """Load the MCMC chains from a hdf5 file. The burn-in points are not rejected at this stage.

        Returns
        -------
        chains: np.array
            Array of the chains.
        lnprobs: np.array
            Array of the logarithmic posterior probability.

        """
        self.chains = [[]]
        self.lnprobs = [[]]
        self.nsteps = 0
        # tau = -1
        reader = emcee.backends.HDFBackend(self.emcee_filename)
        try:
            tau = reader.get_autocorr_time()
        except emcee.autocorr.AutocorrError:
            tau = -1
        self.chains = reader.get_chain(discard=0, flat=False, thin=1)
        self.lnprobs = reader.get_log_prob(discard=0, flat=False, thin=1)
        self.nsteps = self.chains.shape[0]
        self.nwalkers = self.chains.shape[1]
        print(f"Auto-correlation time: {tau}")
        print(f"Burn-in: {self.burnin}")
        print(f"Chains shape: {self.chains.shape}")
        print(f"Log prob shape: {self.lnprobs.shape}")
        return self.chains, self.lnprobs

    def build_flat_chains(self):
        """Flatten the chains array and apply burn-in.

        Returns
        -------
        flat_chains: np.array
            Flat chains.

        """
        self.flat_chains = self.chains[self.burnin:, self.valid_chains, :].reshape((-1, self.ndim))
        return self.flat_chains

    def simulate(self, *p):
        """Compute the model prediction given a set of parameters.

        Parameters
        ----------
        p: array_like
            Array of parameters for the computation of the model.

        Returns
        -------
        x: array_like
            The abscisse of the model prediction.
        model: array_like
            The model prediction.
        model_err: array_like
            The uncertainty on the model prediction.

        Examples
        --------
        >>> w = FitWorkspace()
        >>> p = np.zeros(3)
        >>> x, model, model_err = w.simulate(*p)

        .. doctest::
            :hide:
            >>> assert x is not None

        """
        self.x = np.array([])
        self.model = np.array([])
        self.model_err = np.array([])
        return self.x, self.model, self.model_err

    def analyze_chains(self):
        """Load the chains, build the probability densities for the parameters, compute the best fitting values
        and the uncertainties and covariance matrices, and plot.

        """
        self.load_chains()
        self.set_chain_validity()
        self.convergence_tests()
        self.build_flat_chains()
        self.likelihood = self.chain2likelihood()
        self.cov = self.likelihood.cov_matrix
        self.rho = self.likelihood.rho_matrix
        self.p = self.likelihood.mean_vec
        self.simulate(*self.p)
        self.plot_fit()
        figure_name = os.path.splitext(self.emcee_filename)[0] + '_triangle.pdf'
        self.likelihood.triangle_plots(output_filename=figure_name)

    def plot_fit(self):
        """Generic function to plot the result of the fit for 1D curves.

        Returns
        -------
        fig: plt.FigureClass
            The figure.

        """
        fig = plt.figure()
        plt.errorbar(self.x, self.data, yerr=self.err, fmt='ko', label='Data')
        if self.truth is not None:
            x, truth, truth_err = self.simulate(*self.truth)
            plt.plot(self.x, truth, label="Truth")
        plt.plot(self.x, self.model, label='Best fitting model')
        plt.xlabel('$x$')
        plt.ylabel('$y$')
        title = ""
        for i, label in enumerate(self.input_labels):
            if self.cov.size > 0:
                err = np.sqrt(self.cov[i, i])
                formatting_numbers(self.p[i], err, err)
                _, par, err, _ = formatting_numbers(self.p[i], err, err, label=label)
                title += rf"{label} = {par} $\pm$ {err}"
            else:
                title += f"{label} = {self.p[i]:.3g}"
            if i < len(self.input_labels) - 1:
                title += ", "
        plt.title(title)
        plt.legend()
        plt.grid()
        if parameters.DISPLAY:  # pragma: no cover
            plt.show()
        if parameters.PdfPages:
            parameters.PdfPages.savefig()
        return fig

    def chain2likelihood(self, pdfonly=False, walker_index=-1):
        """Convert the chains to a psoterior probability density function via histograms.

        Parameters
        ----------
        pdfonly: bool, optional
            If True, do not compute the covariances and the 2D correlation plots (default: False).
        walker_index: int, optional
            The walker index to plot. If -1, all walkers are selected (default: -1).

        Returns
        -------
        likelihood: np.array
            Posterior density function.

        """
        if walker_index >= 0:
            chains = self.chains[self.burnin:, walker_index, :]
        else:
            chains = self.flat_chains
        rangedim = range(chains.shape[1])
        centers = []
        for i in rangedim:
            centers.append(np.linspace(np.min(chains[:, i]), np.max(chains[:, i]), self.nbins - 1))
        likelihood = Likelihood(centers, labels=self.input_labels, axis_names=self.axis_names, truth=self.truth)
        if walker_index < 0:
            for i in rangedim:
                likelihood.pdfs[i].fill_histogram(chains[:, i], weights=None)
                if not pdfonly:
                    for j in rangedim:
                        if i != j:
                            likelihood.contours[i][j].fill_histogram(chains[:, i], chains[:, j], weights=None)
            output_file = ""
            if self.filename != "":
                output_file = os.path.splitext(self.filename)[0] + "_bestfit.txt"
            likelihood.stats(output=output_file)
        else:
            for i in rangedim:
                likelihood.pdfs[i].fill_histogram(chains[:, i], weights=None)
        return likelihood

    def compute_local_acceptance_rate(self, start_index, last_index, walker_index):
        """Compute the local acceptance rate in a chain.

        Parameters
        ----------
        start_index: int
            Beginning index.
        last_index: int
            End index.
        walker_index: int
            Index of the walker.

        Returns
        -------
        freq: float
            The acceptance rate.

        """
        frequences = []
        test = -2 * self.lnprobs[start_index, walker_index]
        counts = 1
        for index in range(start_index + 1, last_index):
            chi2 = -2 * self.lnprobs[index, walker_index]
            if np.isclose(chi2, test):
                counts += 1
            else:
                frequences.append(float(counts))
                counts = 1
                test = chi2
        frequences.append(counts)
        return 1.0 / np.mean(frequences)

    def set_chain_validity(self):
        """Test the validity of a chain: reject chains whose chi2 is far from the mean of the others.

        Returns
        -------
        valid_chains: list
            List of boolean values, True if the chain is valid, or False if invalid.

        """
        nchains = [k for k in range(self.nwalkers)]
        chisq_averages = []
        chisq_std = []
        for k in nchains:
            chisqs = -2 * self.lnprobs[self.burnin:, k]
            # if np.mean(chisqs) < 1e5:
            chisq_averages.append(np.mean(chisqs))
            chisq_std.append(np.std(chisqs))
        self.global_average = np.mean(chisq_averages)
        self.global_std = np.mean(chisq_std)
        self.valid_chains = [False] * self.nwalkers
        for k in nchains:
            chisqs = -2 * self.lnprobs[self.burnin:, k]
            chisq_average = np.mean(chisqs)
            chisq_std = np.std(chisqs)
            if 3 * self.global_std + self.global_average < chisq_average < 1e5:
                self.valid_chains[k] = False
            elif chisq_std < 0.1 * self.global_std:
                self.valid_chains[k] = False
            else:
                self.valid_chains[k] = True
        return self.valid_chains

    def convergence_tests(self):
        """Compute the convergence tests (Gelman-Rubin, acceptance rate).

        """
        chains = self.chains[self.burnin:, :, :]  # .reshape((-1, self.ndim))
        nchains = [k for k in range(self.nwalkers)]
        fig, ax = plt.subplots(self.ndim + 1, 2, figsize=(16, 7), sharex='all')
        fontsize = 8
        steps = np.arange(self.burnin, self.nsteps)
        # Chi2 vs Index
        print("Chisq statistics:")
        for k in nchains:
            chisqs = -2 * self.lnprobs[self.burnin:, k]
            text = f"\tWalker {k:d}: {float(np.mean(chisqs)):.3f} +/- {float(np.std(chisqs)):.3f}"
            if not self.valid_chains[k]:
                text += " -> excluded"
                ax[self.ndim, 0].plot(steps, chisqs, c='0.5', linestyle='--')
            else:
                ax[self.ndim, 0].plot(steps, chisqs)
            print(text)
        # global_average = np.mean(-2*self.lnprobs[self.valid_chains, self.burnin:])
        # global_std = np.std(-2*self.lnprobs[self.valid_chains, self.burnin:])
        ax[self.ndim, 0].set_ylim(
            [self.global_average - 5 * self.global_std, self.global_average + 5 * self.global_std])
        # Parameter vs Index
        print("Computing Parameter vs Index plots...")
        for i in range(self.ndim):
            ax[i, 0].set_ylabel(self.axis_names[i], fontsize=fontsize)
            for k in nchains:
                if self.valid_chains[k]:
                    ax[i, 0].plot(steps, chains[:, k, i])
                else:
                    ax[i, 0].plot(steps, chains[:, k, i], c='0.5', linestyle='--')
                ax[i, 0].get_yaxis().set_label_coords(-0.05, 0.5)
        ax[self.ndim, 0].set_ylabel(r'$\chi^2$', fontsize=fontsize)
        ax[self.ndim, 0].set_xlabel('Steps', fontsize=fontsize)
        ax[self.ndim, 0].get_yaxis().set_label_coords(-0.05, 0.5)
        # Acceptance rate vs Index
        print("Computing acceptance rate...")
        min_len = self.nsteps
        window = 100
        if min_len > window:
            for k in nchains:
                ARs = []
                indices = []
                for pos in range(self.burnin + window, self.nsteps, window):
                    ARs.append(self.compute_local_acceptance_rate(pos - window, pos, k))
                    indices.append(pos)
                if self.valid_chains[k]:
                    ax[self.ndim, 1].plot(indices, ARs, label=f'Walker {k:d}')
                else:
                    ax[self.ndim, 1].plot(indices, ARs, label=f'Walker {k:d}', c='gray', linestyle='--')
                ax[self.ndim, 1].set_xlabel('Steps', fontsize=fontsize)
                ax[self.ndim, 1].set_ylabel('Aceptance rate', fontsize=fontsize)
                # ax[self.dim + 1, 2].legend(loc='upper left', ncol=2, fontsize=10)
        # Parameter PDFs by chain
        print("Computing chain by chain PDFs...")
        for k in nchains:
            likelihood = self.chain2likelihood(pdfonly=True, walker_index=k)
            likelihood.stats(pdfonly=True, verbose=False)
            # for i in range(self.dim):
            # ax[i, 1].plot(likelihood.pdfs[i].axe.axis, likelihood.pdfs[i].grid, lw=var.LINEWIDTH,
            #               label=f'Walker {k:d}')
            # ax[i, 1].set_xlabel(self.axis_names[i])
            # ax[i, 1].set_ylabel('PDF')
            # ax[i, 1].legend(loc='upper right', ncol=2, fontsize=10)
        # Gelman-Rubin test.py
        if len(nchains) > 1:
            step = max(1, (self.nsteps - self.burnin) // 20)
            self.gelmans = []
            print(f'Gelman-Rubin tests (burnin={self.burnin:d}, step={step:d}, nsteps={self.nsteps:d}):')
            for i in range(self.ndim):
                Rs = []
                lens = []
                for pos in range(self.burnin + step, self.nsteps, step):
                    chain_averages = []
                    chain_variances = []
                    global_average = np.mean(self.chains[self.burnin:pos, self.valid_chains, i])
                    for k in nchains:
                        if not self.valid_chains[k]:
                            continue
                        chain_averages.append(np.mean(self.chains[self.burnin:pos, k, i]))
                        chain_variances.append(np.var(self.chains[self.burnin:pos, k, i], ddof=1))
                    W = np.mean(chain_variances)
                    B = 0
                    for n in range(len(chain_averages)):
                        B += (chain_averages[n] - global_average) ** 2
                    B *= ((pos + 1) / (len(chain_averages) - 1))
                    R = (W * pos / (pos + 1) + B / (pos + 1) * (len(chain_averages) + 1) / len(chain_averages)) / W
                    Rs.append(R - 1)
                    lens.append(pos)
                print(f'\t{self.input_labels[i]}: R-1 = {Rs[-1]:.3f} (l = {lens[-1] - 1:d})')
                self.gelmans.append(Rs[-1])
                ax[i, 1].plot(lens, Rs, lw=1, label=self.axis_names[i])
                ax[i, 1].axhline(0.03, c='k', linestyle='--')
                ax[i, 1].set_xlabel('Walker length', fontsize=fontsize)
                ax[i, 1].set_ylabel('$R-1$', fontsize=fontsize)
                ax[i, 1].set_ylim(0, 0.6)
                # ax[self.dim, 3].legend(loc='best', ncol=2, fontsize=10)
        self.gelmans = np.array(self.gelmans)
        fig.tight_layout()
        plt.subplots_adjust(hspace=0)
        if parameters.DISPLAY:  # pragma: no cover
            plt.show()
        if parameters.PdfPages:
            parameters.PdfPages.savefig()
        figure_name = self.emcee_filename.replace('.h5', '_convergence.pdf')
        print(f'Save figure: {figure_name}')
        fig.savefig(figure_name, dpi=100)

    def print_settings(self):
        """Print the main settings of the FitWorkspace.

        """
        print('************************************')
        print(f"Input file: {self.filename}\nWalkers: {self.nwalkers}\t Steps: {self.nsteps}")
        print(f"Output file: {self.emcee_filename}")
        print('************************************')

    def save_parameters_summary(self, ipar, header=""):
        """Save the best fitting parameter summary in a text file.

        The file name is build from self.file_name, adding the suffix _bestfit.txt.

        Parameters
        ----------
        ipar: list
            The list of parameter indices to save.
        header: str, optional
            A header to add to the file (default: "").
        """
        output_filename = os.path.splitext(self.filename)[0] + "_bestfit.txt"
        f = open(output_filename, 'w')
        txt = self.filename + "\n"
        if header != "":
            txt += header + "\n"
        for k, ip in enumerate(ipar):
            txt += "%s: %s +%s -%s\n" % formatting_numbers(self.p[ip], np.sqrt(self.cov[k, k]),
                                                           np.sqrt(self.cov[k, k]),
                                                           label=self.input_labels[ip])
        for row in self.cov:
            txt += np.array_str(row, max_line_width=20 * self.cov.shape[0]) + '\n'
        self.my_logger.info(f"\n\tSave best fit parameters in {output_filename}.")
        f.write(txt)
        f.close()

    def plot_correlation_matrix(self, ipar=None):
        """Compute and plot a correlation matrix.

        Save the plot if parameters.SAVE is True. The output file name is build from self.file_name,
        adding the suffix _correlation.pdf.

        Parameters
        ----------
        ipar: list, optional
            The list of parameter indices to include in the matrix.

        Examples
        --------
        >>> w = FitWorkspace()
        >>> w.axis_names = ["x", "y", "z"]
        >>> w.cov = np.array([[1,-0.5,0],[-0.5,1,-1],[0,-1,1]])
        >>> w.plot_correlation_matrix()
        """
        if ipar is None:
            ipar = np.arange(self.cov.shape[0]).astype(int)
        fig = plt.figure()
        self.rho = compute_correlation_matrix(self.cov)
        plot_correlation_matrix_simple(plt.gca(), self.rho, axis_names=[self.axis_names[i] for i in ipar])
        if parameters.SAVE and self.filename != "":  # pragma: no cover
            figname = os.path.splitext(self.filename)[0] + "_correlation.pdf"
            self.my_logger.info(f"Save figure {figname}.")
            fig.savefig(figname, dpi=100, bbox_inches='tight')
        if parameters.PdfPages:
            parameters.PdfPages.savefig()  # args from the above here MFL
        if parameters.DISPLAY:  # pragma: no cover
            if self.live_fit:
                plt.draw()
                plt.pause(1e-8)
            else:
                plt.show()

    def weighted_residuals(self, p):
        """Compute the weighted residuals array for a set of model parameters p.

        The uncertainties are assumed to be uncorrelated.

        Parameters
        ----------
        p: array_like
            The array of model parameters.

        Returns
        -------
        residuals: np.array
            The array of weighted residuals.

        """
        x, model, model_err = self.simulate(*p)
        if self.data_cov is None:
            if len(self.outliers) > 0:
                good_indices = self.not_outliers
                model_err = model_err.flatten()[good_indices]
                err = self.err.flatten()[good_indices]
                res = (model.flatten()[good_indices] - self.data.flatten()[good_indices]) / np.sqrt(
                    model_err * model_err + err * err)
            else:
                res = ((model - self.data) / np.sqrt(model_err * model_err + self.err * self.err)).flatten()
        else:
            if self.data_cov.ndim > 2:
                K = self.data_cov.shape[0]
                cov = [self.data_cov[k] + np.diag(model_err[k] ** 2) for k in range(K)]
                L = [np.linalg.inv(np.linalg.cholesky(cov[k])) for k in range(K)]
                res = np.asarray([L[k] @ (model[k] - self.data[k]) for k in range(K)])
                res = res.flatten()
            else:
                cov = self.data_cov + np.diag(model_err * model_err)
                if len(self.outliers) > 0:
                    good_indices = np.asarray(self.not_outliers, dtype=int)
                    cov = cov[good_indices[:, None], good_indices]
                    L = np.linalg.inv(np.linalg.cholesky(cov))
                    res = L @ (model[good_indices] - self.data[good_indices])
                else:
                    L = np.linalg.inv(np.linalg.cholesky(cov))
                    res = L @ (model - self.data)
        return res

    def chisq(self, p):
        """Compute the chi square for a set of model parameters p.

        Parameters
        ----------
        p: array_like
            The array of model parameters.

        Returns
        -------
        chisq: float
            The chi square value.

        """
        res = self.weighted_residuals(p)
        chisq = np.sum(res * res)
        return chisq

    def lnlike(self, p):
        """Compute the logarithmic likelihood for a set of model parameters p as -0.5*chisq.

        Parameters
        ----------
        p: array_like
            The array of model parameters.

        Returns
        -------
        lnlike: float
            The logarithmic likelihood value.

        """
        return -0.5 * self.chisq(p)

    def lnprior(self, p):
        """Compute the logarithmic prior for a set of model parameters p.

        The function returns 0 for good parameters, and -np.inf for parameters out of their boundaries.

        Parameters
        ----------
        p: array_like
            The array of model parameters.

        Returns
        -------
        lnprior: float
            The logarithmic value fo the prior.

        """
        in_bounds = True
        for npar, par in enumerate(p):
            if par < self.bounds[npar][0] or par > self.bounds[npar][1]:
                in_bounds = False
                break
        if in_bounds:
            return 0.0
        else:
            return -np.inf

    def jacobian(self, params, epsilon, fixed_params=None):
        """Generic function to compute the Jacobian matrix of a model, with numerical derivatives.

        Parameters
        ----------
        params: array_like
            The array of model parameters.
        epsilon: array_like
            The array of small steps to compute the partial derivatives of the model.
        fixed_params: array_like
            List of boolean values. If True, the parameter is considered fixed and no derivative are computed.

        Returns
        -------
        J: np.array
            The Jacobian matrix.

        """
        x, model, model_err = self.simulate(*params)
        model = model.flatten()[self.not_outliers]
        J = np.zeros((params.size, model.size))
        for ip, p in enumerate(params):
            if fixed_params[ip]:
                continue
            tmp_p = np.copy(params)
            if tmp_p[ip] + epsilon[ip] < self.bounds[ip][0] or tmp_p[ip] + epsilon[ip] > self.bounds[ip][1]:
                epsilon[ip] = - epsilon[ip]
            tmp_p[ip] += epsilon[ip]
            tmp_x, tmp_model, tmp_model_err = self.simulate(*tmp_p)
            J[ip] = (tmp_model.flatten()[self.not_outliers] - model) / epsilon[ip]
        return J

    def hessian(self, params, epsilon, fixed_params=None):
        """Experimental function to compute the hessian of a model.

        Parameters
        ----------
        params: array_like
            The array of model parameters.
        epsilon: array_like
            The array of small steps to compute the partial derivatives of the model.
        fixed_params: array_like
            List of boolean values. If True, the parameter is considered fixed and no derivative are computed.

        Returns
        -------

        """
        x, model, model_err = self.simulate(*params)
        model = model.flatten()[self.not_outliers]
        J = self.jacobian(params, epsilon, fixed_params=fixed_params)
        H = np.zeros((params.size, params.size, model.size))
        tmp_p = np.copy(params)
        for ip, p1 in enumerate(params):
            print(ip, p1, params[ip], tmp_p[ip], self.bounds[ip], epsilon[ip], tmp_p[ip] + epsilon[ip])
            if fixed_params[ip]:
                continue
            if tmp_p[ip] + epsilon[ip] < self.bounds[ip][0] or tmp_p[ip] + epsilon[ip] > self.bounds[ip][1]:
                epsilon[ip] = - epsilon[ip]
            tmp_p[ip] += epsilon[ip]
            print(tmp_p)
            # tmp_x, tmp_model, tmp_model_err = self.simulate(*tmp_p)
            # J[ip] = (tmp_model.flatten()[self.not_outliers] - model) / epsilon[ip]
        tmp_J = self.jacobian(tmp_p, epsilon, fixed_params=fixed_params)
        for ip, p1 in enumerate(params):
            if fixed_params[ip]:
                continue
            for jp, p2 in enumerate(params):
                if fixed_params[jp]:
                    continue
                x, modelplus, model_err = self.simulate(params + epsilon)
                x, modelmoins, model_err = self.simulate(params - epsilon)
                model = model.flatten()[self.not_outliers]

                print("hh", ip, jp, tmp_J[ip], J[jp], tmp_p[ip], params, (tmp_J[ip] - J[jp]) / epsilon)
                print((modelplus + modelmoins - 2 * model) / (np.asarray(epsilon) ** 2))
                H[ip, jp] = (tmp_J[ip] - J[jp]) / epsilon
                H[ip, jp] = (modelplus + modelmoins - 2 * model) / (np.asarray(epsilon) ** 2)
        return H


def lnprob(p):  # pragma: no cover
    global fit_workspace
    lp = fit_workspace.lnprior(p)
    if not np.isfinite(lp):
        return -1e20
    return lp + fit_workspace.lnlike(p)


def gradient_descent(fit_workspace, params, epsilon, niter=10, fixed_params=None, xtol=1e-3, ftol=1e-3,
                     with_line_search=True):  # pragma: no cover
    """

    Parameters
    ----------
    fit_workspace: FitWorkspace
    params
    epsilon
    niter
    fixed_params
    xtol
    ftol

    Returns
    -------

    """
    my_logger = set_logger(__name__)
    tmp_params = np.copy(params)
    # Prepare covariance matrix for data
    if fit_workspace.data_cov is None:
        cov_data = np.asarray(fit_workspace.err.flatten()[fit_workspace.not_outliers] ** 2)
    else:
        good_indices = np.asarray(fit_workspace.not_outliers, dtype=int)
        cov_data = np.copy(fit_workspace.data_cov)
        if cov_data.ndim == 2:
            cov_data = cov_data[good_indices[:, None], good_indices]
        elif cov_data.ndim == 3:
            cov_data = [cov_data[k][good_indices[:, None], good_indices] for k in range(cov_data.shape[0])]
        else:
            raise ValueError(f"Data covariance matrix must be of dimension 1, 2 or 3. "
                             f"Here cov_data.ndim=={cov_data.ndim}.")
    # Prepare inverse covariance matrix for data
    W = np.zeros_like(cov_data)
    if fit_workspace.data_invcov is None:
        if cov_data.ndim == 1:
            W = 1 / cov_data
        elif cov_data.ndim == 2:
            L = np.linalg.inv(np.linalg.cholesky(cov_data))
            W = L.T @ L
        elif cov_data.ndim == 3:
            for k in range(cov_data.shape[0]):
                L = np.linalg.inv(np.linalg.cholesky(cov_data[k]))
                W[k] = L.T @ L
    else:
        good_indices = np.asarray(fit_workspace.not_outliers, dtype=int)
        W = np.copy(fit_workspace.data_invcov)
        if W.ndim == 1:
            W = W[good_indices]
        elif W.ndim == 2:
            W = W[good_indices[:, None], good_indices]
        elif W.ndim == 3:
            W = [W[k][good_indices[:, None], good_indices] for k in range(W.shape[0])]
        else:
            raise ValueError(f"Data inverse covariance matrix must be of dimension 1, 2 or 3. Here W.ndim=={W.ndim}.")
    ipar = np.arange(params.size)
    if fixed_params is not None:
        ipar = np.array(np.where(np.array(fixed_params).astype(int) == 0)[0])
    costs = []
    params_table = []
    inv_JT_W_J = np.zeros((len(ipar), len(ipar)))
    for i in range(niter):
        start = time.time()
        tmp_lambdas, tmp_model, tmp_model_err = fit_workspace.simulate(*tmp_params)
        # if fit_workspace.live_fit:
        #    fit_workspace.plot_fit()
        residuals = (tmp_model - fit_workspace.data).flatten()[fit_workspace.not_outliers]
        if cov_data.ndim == 1:
            if np.any(tmp_model_err > 0):
                cov = cov_data + np.asarray(tmp_model_err.flatten()[fit_workspace.not_outliers] ** 2)
                W = 1 / cov
            cost = residuals @ (W * residuals)
        elif cov_data.ndim == 2:
            if np.any(tmp_model_err > 0):
                cov = cov_data + np.diag(tmp_model_err.flatten()[fit_workspace.not_outliers] ** 2)
                L = np.linalg.inv(np.linalg.cholesky(cov))
                W = L.T @ L
            cost = residuals @ W @ residuals
        elif cov_data.ndim == 3:
            if np.any(tmp_model_err > 0):
                cov = np.asarray([cov_data[k] + np.diag(tmp_model_err.flatten()[fit_workspace.not_outliers] ** 2)
                                  for k in range(cov_data.shape[0])])
                W = np.zeros_like(cov)
                for k in range(cov.shape[0]):
                    L = np.linalg.inv(np.linalg.cholesky(cov[k]))
                    W[k] = L.T @ L
        # Jacobian
        J = fit_workspace.jacobian(tmp_params, epsilon, fixed_params=fixed_params)
        # remove parameters with unexpected null Jacobian vectors
        for ip in range(J.shape[0]):
            if ip not in ipar:
                continue
            if np.all(J[ip] == np.zeros(J.shape[1])):
                ipar = np.delete(ipar, list(ipar).index(ip))
                fixed_params[ip] = True
                # tmp_params[ip] = 0
                my_logger.warning(
                    f"\n\tStep {i}: {fit_workspace.input_labels[ip]} has a null Jacobian; parameter is fixed "
                    f"at its last known current value ({tmp_params[ip]}).")
        # remove fixed parameters
        J = J[ipar].T
        # algebra
        if W.ndim == 1:
            JT_W = J.T * W
        elif W.ndim == 2:
            JT_W = J.T @ W
        else:
            JT_W = np.array([J.T[k] @ W[k] for k in range(W.shape[0])])
        JT_W_J = JT_W @ J
        try:
            L = np.linalg.inv(np.linalg.cholesky(JT_W_J))  # cholesky is too sensible to the numerical precision
            inv_JT_W_J = L.T @ L
        except np.linalg.LinAlgError:
            inv_JT_W_J = np.linalg.inv(JT_W_J)
        JT_W_R0 = JT_W @ residuals
        dparams = - inv_JT_W_J @ JT_W_R0

        if with_line_search:
            def line_search(alpha):
                tmp_params_2 = np.copy(tmp_params)
                tmp_params_2[ipar] = tmp_params[ipar] + alpha * dparams
                for ipp, pp in enumerate(tmp_params_2):
                    if pp < fit_workspace.bounds[ipp][0]:
                        tmp_params_2[ipp] = fit_workspace.bounds[ipp][0]
                    if pp > fit_workspace.bounds[ipp][1]:
                        tmp_params_2[ipp] = fit_workspace.bounds[ipp][1]
                # lbd, mod, err = fit_workspace.simulate(*tmp_params_2)
                # res = mod.flatten()[fit_workspace.not_outliers] - fit_workspace.data.flatten()[fit_workspace.not_outliers]
                w_res = fit_workspace.weighted_residuals(tmp_params_2)
                return w_res @ w_res  # res @ (W * res)

            # tol parameter acts on alpha (not func)
            alpha_min, fval, iter, funcalls = optimize.brent(line_search, full_output=True, tol=5e-1, brack=(0, 1))
        else:
            alpha_min = 1
            fval = np.copy(cost)
            funcalls = 0
            iter = 0
        tmp_params[ipar] += alpha_min * dparams
        # check bounds
        for ip, p in enumerate(tmp_params):
            if p < fit_workspace.bounds[ip][0]:
                tmp_params[ip] = fit_workspace.bounds[ip][0]
            if p > fit_workspace.bounds[ip][1]:
                tmp_params[ip] = fit_workspace.bounds[ip][1]
        # prepare outputs
        costs.append(fval)
        params_table.append(np.copy(tmp_params))
        if fit_workspace.verbose:
            my_logger.info(f"\n\tIteration={i}: initial cost={cost:.5g} initial chisq_red={cost / tmp_model.size:.5g}"
                           f"\n\t\t Line search: alpha_min={alpha_min:.3g} iter={iter} funcalls={funcalls}"
                           f"\n\tParameter shifts: {alpha_min * dparams}"
                           f"\n\tNew parameters: {tmp_params[ipar]}"
                           f"\n\tFinal cost={fval:.5g} final chisq_red={fval / tmp_model.size:.5g} "
                           f"computed in {time.time() - start:.2f}s")
        if fit_workspace.live_fit:  # pragma: no cover
            fit_workspace.simulate(*tmp_params)
            fit_workspace.plot_fit()
            fit_workspace.cov = inv_JT_W_J
            # fit_workspace.plot_correlation_matrix(ipar)
        if len(ipar) == 0:
            my_logger.warning(f"\n\tGradient descent terminated in {i} iterations because all parameters "
                              f"have null Jacobian.")
            break
        if fit_workspace.verbose or parameters.DEBUG:
            if np.sum(np.abs(alpha_min * dparams)) / np.sum(np.abs(tmp_params[ipar])) < xtol:
                my_logger.info(f"\n\tGradient descent terminated in {i} iterations because the sum of parameter shift "
                               f"relative to the sum of the parameters is below xtol={xtol}.")
                break
            if len(costs) > 1 and np.abs(costs[-2] - fval) / np.max([np.abs(fval), np.abs(costs[-2])]) < ftol:
                my_logger.info(f"\n\tGradient descent terminated in {i} iterations because the "
                               f"relative change of cost is below ftol={ftol}.")
                break
    plt.close()
    return tmp_params, inv_JT_W_J, np.array(costs), np.array(params_table)


def simple_newton_minimisation(fit_workspace, params, epsilon, niter=10, fixed_params=None,
                               xtol=1e-3, ftol=1e-3):  # pragma: no cover
    """Experimental function to minimize a function.

    Parameters
    ----------
    fit_workspace: FitWorkspace
    params
    epsilon
    niter
    fixed_params
    xtol
    ftol

    Returns
    -------

    """
    my_logger = set_logger(__name__)
    tmp_params = np.copy(params)
    ipar = np.arange(params.size)
    if fixed_params is not None:
        ipar = np.array(np.where(np.array(fixed_params).astype(int) == 0)[0])
    funcs = []
    params_table = []
    inv_H = np.zeros((len(ipar), len(ipar)))
    for i in range(niter):
        start = time.time()
        tmp_lambdas, tmp_model, tmp_model_err = fit_workspace.simulate(*tmp_params)
        # if fit_workspace.live_fit:
        #    fit_workspace.plot_fit()
        J = fit_workspace.jacobian(tmp_params, epsilon, fixed_params=fixed_params)
        # remove parameters with unexpected null Jacobian vectors
        for ip in range(J.shape[0]):
            if ip not in ipar:
                continue
            if np.all(J[ip] == np.zeros(J.shape[1])):
                ipar = np.delete(ipar, list(ipar).index(ip))
                # tmp_params[ip] = 0
                my_logger.warning(
                    f"\n\tStep {i}: {fit_workspace.input_labels[ip]} has a null Jacobian; parameter is fixed "
                    f"at its last known current value ({tmp_params[ip]}).")
        # remove fixed parameters
        J = J[ipar].T
        # hessian
        H = fit_workspace.hessian(tmp_params, epsilon, fixed_params=fixed_params)
        try:
            L = np.linalg.inv(np.linalg.cholesky(H))  # cholesky is too sensible to the numerical precision
            inv_H = L.T @ L
        except np.linalg.LinAlgError:
            inv_H = np.linalg.inv(H)
        dparams = - inv_H[:, :, 0] @ J[:, 0]
        print("dparams", dparams, inv_H, J, H)
        tmp_params[ipar] += dparams

        # check bounds
        print("tmp_params", tmp_params, dparams, inv_H, J)
        for ip, p in enumerate(tmp_params):
            if p < fit_workspace.bounds[ip][0]:
                tmp_params[ip] = fit_workspace.bounds[ip][0]
            if p > fit_workspace.bounds[ip][1]:
                tmp_params[ip] = fit_workspace.bounds[ip][1]

        tmp_lambdas, new_model, tmp_model_err = fit_workspace.simulate(*tmp_params)
        new_func = new_model[0]
        funcs.append(new_func)

        r = np.log10(fit_workspace.regs)
        js = [fit_workspace.jacobian(np.asarray([rr]), epsilon, fixed_params=fixed_params)[0] for rr in np.array(r)]
        plt.plot(r, js, label="J")
        plt.grid()
        plt.legend()
        plt.show()

        if parameters.DISPLAY:
            fig = plt.figure()
            plt.plot(r, js, label="prior")
            mod = tmp_model + J[0] * (r - (tmp_params - dparams)[0])
            plt.plot(r, mod)
            plt.axvline(tmp_params)
            plt.axhline(tmp_model)
            plt.grid()
            plt.legend()
            plt.draw()
            plt.pause(1e-8)
            plt.close(fig)

        # prepare outputs
        params_table.append(np.copy(tmp_params))
        if fit_workspace.verbose:
            my_logger.info(f"\n\tIteration={i}: initial func={tmp_model[0]:.5g}"
                           f"\n\tParameter shifts: {dparams}"
                           f"\n\tNew parameters: {tmp_params[ipar]}"
                           f"\n\tFinal func={new_func:.5g}"
                           f" computed in {time.time() - start:.2f}s")
        if fit_workspace.live_fit:
            fit_workspace.simulate(*tmp_params)
            fit_workspace.plot_fit()
            fit_workspace.cov = inv_H[:, :, 0]
            print("shape", fit_workspace.cov.shape)
            # fit_workspace.plot_correlation_matrix(ipar)
        if len(ipar) == 0:
            my_logger.warning(f"\n\tGradient descent terminated in {i} iterations because all parameters "
                              f"have null Jacobian.")
            break
        if fit_workspace.verbose or parameters.DEBUG:
            if np.sum(np.abs(dparams)) / np.sum(np.abs(tmp_params[ipar])) < xtol:
                my_logger.info(f"\n\tGradient descent terminated in {i} iterations because the sum of parameter shift "
                               f"relative to the sum of the parameters is below xtol={xtol}.")
                break
            if len(funcs) > 1 and np.abs(funcs[-2] - new_func) / np.max([np.abs(new_func), np.abs(funcs[-2])]) < ftol:
                my_logger.info(f"\n\tGradient descent terminated in {i} iterations because the "
                               f"relative change of cost is below ftol={ftol}.")
                break
    plt.close()
    return tmp_params, inv_H[:, :, 0], np.array(funcs), np.array(params_table)


def print_parameter_summary(params, cov, labels):
    """Print the best fitting parameters on screen.

    Parameters
    ----------
    params: array_like
        The best fitting parameter values.
    cov: array_like
        The associated covariance matrix.
    labels: array_like
        The list of associated parameter labels.
    """
    my_logger = set_logger(__name__)
    txt = ""
    for ip in np.arange(0, cov.shape[0]).astype(int):
        txt += "%s: %s +%s -%s\n\t" % formatting_numbers(params[ip], np.sqrt(cov[ip, ip]), np.sqrt(cov[ip, ip]),
                                                         label=labels[ip])
    my_logger.info(f"\n\t{txt}")


def plot_gradient_descent(fit_workspace, costs, params_table):
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex="all")
    iterations = np.arange(params_table.shape[0])
    ax[0].plot(iterations, costs, lw=2)
    for ip in range(params_table.shape[1]):
        ax[1].plot(iterations, params_table[:, ip], label=f"{fit_workspace.axis_names[ip]}")
    ax[1].set_yscale("symlog")
    ax[1].legend(ncol=6, loc=9)
    ax[1].grid()
    ax[0].set_yscale("log")
    ax[0].set_ylabel(r"$\chi^2$")
    ax[1].set_ylabel("Parameters")
    ax[0].grid()
    ax[1].set_xlabel("Iterations")
    ax[0].xaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout()
    plt.subplots_adjust(wspace=0, hspace=0)
    if parameters.SAVE and fit_workspace.filename != "":  # pragma: no cover
        figname = os.path.splitext(fit_workspace.filename)[0] + "_fitting.pdf"
        fit_workspace.my_logger.info(f"\n\tSave figure {figname}.")
        fig.savefig(figname, dpi=100, bbox_inches='tight')
    if parameters.DISPLAY:  # pragma: no cover
        plt.show()
    if parameters.PdfPages:  # args from the above? MFL
        parameters.PdfPages.savefig()

    fit_workspace.simulate(*fit_workspace.p)
    fit_workspace.live_fit = False
    fit_workspace.plot_fit()


def save_gradient_descent(fit_workspace, costs, params_table):
    iterations = np.arange(params_table.shape[0]).astype(int)
    t = np.zeros((params_table.shape[1] + 2, params_table.shape[0]))
    t[0] = iterations
    t[1] = costs
    t[2:] = params_table.T
    h = 'iter,costs,' + ','.join(fit_workspace.input_labels)
    output_filename = os.path.splitext(fit_workspace.filename)[0] + "_fitting.txt"
    np.savetxt(output_filename, t.T, header=h, delimiter=",")
    fit_workspace.my_logger.info(f"\n\tSave gradient descent log {output_filename}.")


def run_gradient_descent(fit_workspace, guess, epsilon, params_table, costs, fix, xtol, ftol, niter, verbose=False,
                         with_line_search=True):
    fit_workspace.p, fit_workspace.cov, tmp_costs, tmp_params_table = gradient_descent(fit_workspace, guess,
                                                                                       epsilon, niter=niter,
                                                                                       fixed_params=fix,
                                                                                       xtol=xtol, ftol=ftol,
                                                                                       with_line_search=with_line_search)
    params_table = np.concatenate([params_table, tmp_params_table])
    costs = np.concatenate([costs, tmp_costs])
    ipar = np.array(np.where(np.array(fix).astype(int) == 0)[0])
    if verbose or fit_workspace.verbose:
        print_parameter_summary(fit_workspace.p[ipar], fit_workspace.cov,
                                [fit_workspace.input_labels[ip] for ip in ipar])
    if parameters.DEBUG and (verbose or fit_workspace.verbose):
        # plot_psf_poly_params(fit_workspace.p[fit_workspace.psf_params_start_index:])
        # fit_workspace.plot_fit()
        plot_gradient_descent(fit_workspace, costs, params_table)
        if len(ipar) > 1:
            fit_workspace.plot_correlation_matrix(ipar=ipar)
    return params_table, costs


def run_simple_newton_minimisation(fit_workspace, guess, epsilon, fix=None, xtol=1e-8, ftol=1e-8,
                                   niter=50, verbose=False):  # pragma: no cover
    if fix is None:
        fix = [False] * guess.size
    fit_workspace.p, fit_workspace.cov, funcs, params_table = simple_newton_minimisation(fit_workspace, guess,
                                                                                         epsilon, niter=niter,
                                                                                         fixed_params=fix,
                                                                                         xtol=xtol, ftol=ftol)
    ipar = np.array(np.where(np.array(fix).astype(int) == 0)[0])
    if verbose or fit_workspace.verbose:
        print_parameter_summary(fit_workspace.p[ipar], fit_workspace.cov,
                                [fit_workspace.input_labels[ip] for ip in ipar])
    if parameters.DEBUG and (verbose or fit_workspace.verbose):
        # plot_psf_poly_params(fit_workspace.p[fit_workspace.psf_params_start_index:])
        # fit_workspace.plot_fit()
        plot_gradient_descent(fit_workspace, funcs, params_table)
        if len(ipar) > 1:
            fit_workspace.plot_correlation_matrix(ipar=ipar)
    return params_table, funcs


def run_minimisation(fit_workspace, method="newton", epsilon=None, fix=None, xtol=1e-4, ftol=1e-4, niter=50,
                     verbose=False, with_line_search=True, minimizer_method="L-BFGS-B"):
    my_logger = set_logger(__name__)

    bounds = fit_workspace.bounds

    nll = lambda params: -fit_workspace.lnlike(params)

    guess = fit_workspace.p.astype('float64')
    if verbose:
        my_logger.debug(f"\n\tStart guess: {guess}")

    if method == "minimize":
        start = time.time()
        result = optimize.minimize(nll, fit_workspace.p, method=minimizer_method,
                                   options={'ftol': ftol, 'gtol': 1e-20,
                                            'maxiter': 100000, 'maxls': 50, 'maxcor': 30},
                                   bounds=bounds)
        fit_workspace.p = result['x']
        if verbose:
            my_logger.debug(f"\n\t{result}")
            my_logger.debug(f"\n\tMinimize: total computation time: {time.time() - start}s")
            fit_workspace.plot_fit()
    elif method == 'basinhopping':
        start = time.time()
        minimizer_kwargs = dict(method=minimizer_method, bounds=bounds)
        result = optimize.basinhopping(nll, guess, minimizer_kwargs=minimizer_kwargs)
        fit_workspace.p = result['x']
        if verbose:
            my_logger.debug(f"\n\t{result}")
            my_logger.debug(f"\n\tBasin-hopping: total computation time: {time.time() - start}s")
            fit_workspace.plot_fit()
    elif method == "least_squares":
        start = time.time()
        x_scale = np.abs(guess)
        x_scale[x_scale == 0] = 0.1
        p = optimize.least_squares(fit_workspace.weighted_residuals, guess, verbose=2, ftol=1e-6, x_scale=x_scale,
                                   diff_step=0.001, bounds=bounds.T)
        fit_workspace.p = p.x  # m.np_values()
        if verbose:
            my_logger.debug(f"\n\t{p}")
            my_logger.debug(f"\n\tLeast_squares: total computation time: {time.time() - start}s")
            fit_workspace.plot_fit()
    elif method == "minuit":
        start = time.time()
        # fit_workspace.simulation.fix_psf_cube = False
        error = 0.1 * np.abs(guess) * np.ones_like(guess)
        error[2:5] = 0.3 * np.abs(guess[2:5]) * np.ones_like(guess[2:5])
        z = np.where(np.isclose(error, 0.0, 1e-6))
        error[z] = 1.
        if fix is None:
            fix = [False] * guess.size
        # noinspection PyArgumentList
        m = Minuit.from_array_func(fcn=nll, start=guess, error=error, errordef=1,
                                   fix=fix, print_level=verbose, limit=bounds)
        m.tol = 10
        m.migrad()
        fit_workspace.p = m.np_values()
        if verbose:
            my_logger.debug(f"\n\t{m}")
            my_logger.debug(f"\n\tMinuit: total computation time: {time.time() - start}s")
            fit_workspace.plot_fit()
    elif method == "newton":
        if fit_workspace.costs.size == 0:
            costs = np.array([fit_workspace.chisq(guess)])
            params_table = np.array([guess])
        else:
            costs = np.concatenate([fit_workspace.costs, np.array([fit_workspace.chisq(guess)])])
            params_table = np.concatenate([fit_workspace.params_table, np.array([guess])])
        if epsilon is None:
            epsilon = 1e-4 * guess
            epsilon[epsilon == 0] = 1e-4
        if fix is None:
            fix = [False] * guess.size

        start = time.time()
        params_table, costs = run_gradient_descent(fit_workspace, guess, epsilon, params_table, costs,
                                                   fix=fix, xtol=xtol, ftol=ftol, niter=niter, verbose=verbose,
                                                   with_line_search=with_line_search)
        fit_workspace.costs = costs
        fit_workspace.params_table = params_table
        if verbose:
            my_logger.debug(f"\n\tNewton: total computation time: {time.time() - start}s")
        if fit_workspace.filename != "":
            ipar = np.array(np.where(np.array(fit_workspace.fixed).astype(int) == 0)[0])
            fit_workspace.save_parameters_summary(ipar)
            save_gradient_descent(fit_workspace, costs, params_table)


def run_minimisation_sigma_clipping(fit_workspace, method="newton", epsilon=None, fix=None, xtol=1e-4, ftol=1e-4,
                                    niter=50, sigma_clip=5.0, niter_clip=3, verbose=False):
    my_logger = set_logger(__name__)
    fit_workspace.sigma_clip = sigma_clip
    for step in range(niter_clip):
        if verbose:
            my_logger.info(f"\n\tSigma-clipping step {step}/{niter_clip} (sigma={sigma_clip})")
        run_minimisation(fit_workspace, method=method, epsilon=epsilon, fix=fix, xtol=xtol, ftol=ftol, niter=niter)
        # remove outliers
        indices_no_nan = ~np.isnan(fit_workspace.data)
        residuals = np.abs(fit_workspace.model[indices_no_nan]
                           - fit_workspace.data[indices_no_nan]) / fit_workspace.err[indices_no_nan]
        outliers = residuals > sigma_clip
        outliers = [i for i in range(fit_workspace.data.size) if outliers[i]]
        outliers.sort()
        if len(outliers) > 0:
            my_logger.debug(f'\n\tOutliers flat index list:\n{outliers}')
            my_logger.info(f'\n\tOutliers: {len(outliers)} / {fit_workspace.data.size} data points '
                           f'({100 * len(outliers) / fit_workspace.data.size:.2f}%) '
                           f'at more than {sigma_clip}-sigma from best-fit model.')
            if np.all(fit_workspace.outliers == outliers):
                my_logger.info(f'\n\tOutliers flat index list unchanged since last iteration: '
                               f'break the sigma clipping iterations.')
                break
            else:
                fit_workspace.outliers = outliers
        else:
            my_logger.info(f'\n\tNo outliers detected at first iteration: break the sigma clipping iterations.')
            break


def run_emcee(fit_workspace, ln=lnprob):
    my_logger = set_logger(__name__)
    fit_workspace.print_settings()
    nsamples = fit_workspace.nsteps
    p0 = fit_workspace.set_start()
    filename = fit_workspace.emcee_filename
    backend = emcee.backends.HDFBackend(filename)
    try:  # pragma: no cover
        pool = MPIPool()
        if not pool.is_master():
            pool.wait()
            sys.exit(0)
        sampler = emcee.EnsembleSampler(fit_workspace.nwalkers, fit_workspace.ndim, ln, args=(),
                                        pool=pool, backend=backend)
        my_logger.info(f"\n\tInitial size: {backend.iteration}")
        if backend.iteration > 0:
            p0 = backend.get_last_sample()
        if nsamples - backend.iteration > 0:
            sampler.run_mcmc(p0, nsteps=max(0, nsamples - backend.iteration), progress=True)
        pool.close()
    except ValueError:
        sampler = emcee.EnsembleSampler(fit_workspace.nwalkers, fit_workspace.ndim, ln, args=(),
                                        threads=multiprocessing.cpu_count(), backend=backend)
        my_logger.info(f"\n\tInitial size: {backend.iteration}")
        if backend.iteration > 0:
            p0 = sampler.get_last_sample()
        for _ in sampler.sample(p0, iterations=max(0, nsamples - backend.iteration), progress=True, store=True):
            continue
    fit_workspace.chains = sampler.chain
    fit_workspace.lnprobs = sampler.lnprobability


class RegFitWorkspace(FitWorkspace):

    def __init__(self, w, opt_reg=parameters.PSF_FIT_REG_PARAM, verbose=False, live_fit=False):
        """

        Parameters
        ----------
        w: ChromaticPSFFitWorkspace
        """
        FitWorkspace.__init__(self, verbose=verbose, live_fit=live_fit)
        self.x = np.array([0])
        self.data = np.array([0])
        self.err = np.array([1])
        self.w = w
        self.p = np.asarray([np.log10(opt_reg)])
        self.bounds = [(-20, np.log10(self.w.amplitude_priors.size) + 2)]
        self.input_labels = ["log10_reg"]
        self.axis_names = [r"$\log_{10} r$"]
        self.fixed = [False] * self.p.size
        self.opt_reg = opt_reg
        self.resolution = np.zeros_like((self.w.amplitude_params.size, self.w.amplitude_params.size))
        self.G = 0
        self.chisquare = -1

    def simulate(self, log10_r):
        reg = 10 ** log10_r
        M_dot_W_dot_M_plus_Q = self.w.M_dot_W_dot_M + reg * self.w.Q
        try:
            L = np.linalg.inv(np.linalg.cholesky(M_dot_W_dot_M_plus_Q))
            cov = L.T @ L
        except np.linalg.LinAlgError:
            cov = np.linalg.inv(M_dot_W_dot_M_plus_Q)
        A = cov @ (self.w.M.T @ self.w.W_dot_data + reg * self.w.Q_dot_A0)
        self.resolution = np.eye(A.size) - reg * cov @ self.w.Q
        diff = self.w.data_flat - self.w.M @ A
        self.chisquare = diff[self.w.not_outliers] @ (self.w.W * diff)[self.w.not_outliers]
        self.w.amplitude_params = A
        self.w.amplitude_cov_matrix = cov
        self.w.amplitude_params_err = np.array([np.sqrt(cov[x, x]) for x in range(cov.shape[0])])
        self.G = self.chisquare / (self.w.data_flat.size - np.trace(self.resolution)) ** 2
        return np.asarray([log10_r]), np.asarray([self.G]), np.zeros_like(self.data)

    def plot_fit(self):
        log10_opt_reg = self.p[0]
        opt_reg = 10 ** log10_opt_reg
        regs = 10 ** np.linspace(min(-10, 0.9 * log10_opt_reg), max(3, 1.2 * log10_opt_reg), 50)
        Gs = []
        chisqs = []
        resolutions = []
        x = np.arange(len(self.w.amplitude_priors))
        for r in regs:
            self.simulate(np.log10(r))
            if parameters.DISPLAY and False:
                fig = plt.figure()
                plt.errorbar(x, self.w.amplitude_params, yerr=[np.sqrt(self.w.amplitude_cov_matrix[i, i]) for i in x],
                             label=f"fit r={r:.2g}")
                plt.plot(x, self.w.amplitude_priors, label="prior")
                plt.grid()
                plt.legend()
                plt.draw()
                plt.pause(1e-8)
                plt.close(fig)
            Gs.append(self.G)
            chisqs.append(self.chisquare)
            resolutions.append(np.trace(self.resolution))
        fig, ax = plt.subplots(3, 1, figsize=(7, 5), sharex="all")
        ax[0].plot(regs, Gs)
        ax[0].axvline(opt_reg, color="k")
        ax[1].axvline(opt_reg, color="k")
        ax[2].axvline(opt_reg, color="k")
        ax[0].set_ylabel(r"$G(r)$")
        ax[0].set_xlabel("Regularisation hyper-parameter $r$")
        ax[0].grid()
        ax[0].set_title(f"Optimal regularisation parameter: {opt_reg:.3g}")
        ax[1].plot(regs, chisqs)
        ax[1].set_ylabel(r"$\chi^2(\mathbf{A}(r) \vert \mathbf{\theta})$")
        ax[1].set_xlabel("Regularisation hyper-parameter $r$")
        ax[1].grid()
        ax[1].set_xscale("log")
        ax[2].set_xscale("log")
        ax[2].plot(regs, resolutions)
        ax[2].set_ylabel(r"$\mathrm{Tr}\,\mathbf{R}$")
        ax[2].set_xlabel("Regularisation hyper-parameter $r$")
        ax[2].grid()
        fig.tight_layout()
        plt.subplots_adjust(hspace=0)
        if parameters.DISPLAY:
            plt.show()
        if parameters.LSST_SAVEFIGPATH:
            fig.savefig(os.path.join(parameters.LSST_SAVEFIGPATH, 'regularisation.pdf'))

        fig = plt.figure(figsize=(7, 5))
        rho = compute_correlation_matrix(self.w.amplitude_cov_matrix)
        plot_correlation_matrix_simple(plt.gca(), rho, axis_names=[''] * len(self.w.amplitude_params))
        # ipar=np.arange(10, 20))
        plt.gca().set_title(r"Correlation matrix $\mathbf{\rho}$")
        if parameters.LSST_SAVEFIGPATH:
            fig.savefig(os.path.join(parameters.LSST_SAVEFIGPATH, 'amplitude_correlation_matrix.pdf'))
        if parameters.DISPLAY:
            plt.show()


if __name__ == "__main__":
    import doctest

    doctest.testmod()
