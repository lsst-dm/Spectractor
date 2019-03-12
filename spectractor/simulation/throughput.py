"""
throughput.py
=============----

author : Sylvie Dagoret-Campagne, Jérémy Neveu
affiliation : LAL/CNRS/IN2P3/FRANCE
Collaboration : DESC-LSST

Purpose : Provide the various useful transmission functions
update : July 2018

"""

import os
import matplotlib.pyplot as plt
import numpy as np

import spectractor.parameters as parameters


class Throughput:

    def __init__(self, input_directory=parameters.THROUGHPUT_DIR):
        """Class to load the different instrument transmissions.

        Parameters
        ----------
        input_directory: str
            The directory where the input transmission files are.
        """
        self.path_transmission = input_directory
        self.filename_quantum_efficiency = os.path.join(self.path_transmission, parameters.OBS_QUANTUM_EFFICIENCY)
        # RG715.txt and FGB37.txt are extracted from .gc files.
        self.filename_FGB37 = os.path.join(self.path_transmission, "FGB37.txt")
        self.filename_RG715 = os.path.join(self.path_transmission, "RG715.txt")
        self.filename_telescope_throughput = os.path.join(self.path_transmission, parameters.OBS_TELESCOPE_TRANSMISSION)
        self.filename_mirrors = os.path.join(self.path_transmission, 'lsst_mirrorthroughput.txt')
        self.filename_total_throughput = os.path.join(self.path_transmission,
                                                      parameters.OBS_FULL_INSTRUMENT_TRANSMISSON)
        # self.filename_total_throughput = os.path.join(self.path_transmission,
        # '20171006_RONCHI400_clear_45_median_tpt.txt')

    def load_quantum_efficiency(self):
        """Load the quantum efficiency file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 500
        >>> lambdas, transmissions, errors = t.load_quantum_efficiency()
        >>> print(lambdas[:3])
        [500.81855389 508.18553888 519.23601637]
        >>> print(transmissions[:3])
        [0.74355972 0.75526932 0.76932084]
        >>> print(errors[:3])
        [0. 0. 0.]

        """
        lambdas, transmissions, errors = load_transmission(self.filename_quantum_efficiency)
        return lambdas, transmissions, errors

    def load_RG715(self):
        """Load the quantum efficiency file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 700
        >>> lambdas, transmissions, errors = t.load_RG715()
        >>> print(lambdas[:3])
        [701.899 704.054 705.491]
        >>> print(transmissions[:3])
        [0.09726 0.13538 0.16826]
        >>> print(errors[:3])
        [0. 0. 0.]

        """
        lambdas, transmissions, errors = load_transmission(self.filename_RG715)
        return lambdas, transmissions, errors

    def load_FGB37(self):
        """Load the quantum efficiency file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 500
        >>> lambdas, transmissions, errors = t.load_FGB37()
        >>> print(lambdas[:3])
        [515.171 534.679 545.315]
        >>> print(transmissions[:3])
        [0.89064 0.87043 0.8391 ]
        >>> print(errors[:3])
        [0. 0. 0.]

        """
        lambdas, transmissions, errors = load_transmission(self.filename_FGB37)
        return lambdas, transmissions, errors

    def load_telescope_throughput(self):
        """Load the telescope throughput file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 500
        >>> lambdas, transmissions, errors = t.load_telescope_throughput()
        >>> print(lambdas[:3])
        [501. 502. 503.]
        >>> print(transmissions[:3])
        [0.77987732 0.78065328 0.78097758]
        >>> print(errors[:3])
        [0. 0. 0.]

        """
        lambdas, transmissions, errors = load_transmission(self.filename_telescope_throughput)
        return lambdas, transmissions, errors

    def load_total_throughput(self):
        """Load the telescope throughput file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 500
        >>> lambdas, transmissions, errors = t.load_total_throughput()
        >>> print(lambdas[:3])
        [501. 502. 503.]
        >>> print(transmissions[:3])
        [0.16189332 0.16211692 0.16234082]
        >>> print(errors[:3])
        [0.001309   0.00130761 0.00130621]

        """
        lambdas, transmissions, errors = load_transmission(self.filename_total_throughput)
        return lambdas, transmissions, errors

    def load_mirror_reflectivity(self):
        """Load the telescope throughput file and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

        The input file must have two or three columns:
            1. wavelengths in nm
            2. transmissions between 0 and 1.
            3. uncertainties on the transmissions (optional)

        Returns
        -------
        lambdas: array_like
            The wavelengths array in nm.
        transmissions: array_like
            The transmission array, values are between 0 and 1.
        uncertainties: array_like
            The uncertainty on the transmission array (0 if file does not contain the info).

        Examples
        --------
        >>> t = Throughput()
        >>> parameters.LAMBDA_MIN = 500
        >>> lambdas, transmissions, errors = t.load_mirror_reflectivity()
        >>> print(lambdas[:3])
        [501. 502. 503.]
        >>> print(transmissions[:3])
        [0.93501 0.93527 0.93532]
        >>> print(errors[:3])
        [0. 0. 0.]
        """
        lambdas, transmissions, errors = load_transmission(self.filename_mirrors)
        return lambdas, transmissions, errors


def load_transmission(file_name):
    """Load the transmission files and crop in wavelength using LAMBDA_MIN and LAMBDA_MAX.

    The input file must have two or three columns:
        1. wavelengths in nm
        2. transmissions between 0 and 1.
        3. uncertainties on the transmissions (optional)

    Returns
    -------
    lambdas: array_like
        The wavelengths array in nm.
    transmissions: array_like
        The transmission array, values are between 0 and 1.
    uncertainties: array_like
        The uncertainty on the transmission array (0 if file does not contain the info).

    Examples
    --------
    >>> t = Throughput()
    >>> parameters.LAMBDA_MIN = 500
    >>> lambdas, transmissions, errors = load_transmission(t.filename_quantum_efficiency)
    >>> print(lambdas[:3])
    [500.81855389 508.18553888 519.23601637]
    >>> print(transmissions[:3])
    [0.74355972 0.75526932 0.76932084]
    >>> print(errors[:3])
    [0. 0. 0.]

    """
    data = np.loadtxt(file_name).T
    x = data[0]
    y = data[1]
    err = np.zeros_like(y)
    if data.shape[0] == 3:
        err = data[2]
    indexes = np.where(np.logical_and(x > parameters.LAMBDA_MIN, x < parameters.LAMBDA_MAX))
    return x[indexes], y[indexes], err[indexes]


def plot_transmission_simple(ax, lambdas, transmissions,  uncertainties=None, label="", title="", lw=2):
    """Plot the transmission with respect to the wavelength.

    Parameters
    ----------
    ax: Axes
        An Axes instance.
    lambdas: array_like
        The wavelengths array in nm.
    transmissions: array_like
        The transmission array, values are between 0 and 1.
    uncertainties: array_like, optional
        The uncertainty on the transmission array (default: None).
    label: str, optional
        The label of the curve for the legend (default: "")
    title: str, optional
        The title of the plot (default: "")
    lw: int
        Line width (default: 2).

    Examples
    --------
    >>> fig = plt.figure()
    >>> ax = plt.gca()
    >>> t = Throughput()
    >>> parameters.LAMBDA_MIN = 500
    >>> lambdas, transmissions, errors = t.load_quantum_efficiency()
    >>> plot_transmission_simple(ax, lambdas, transmissions, errors, title="CTIO", label="Quantum efficiency")
    >>> lambdas, transmissions, errors = t.load_mirror_reflectivity()
    >>> plot_transmission_simple(ax, lambdas, transmissions, errors, title="CTIO", label="Mirror 1")
    >>> lambdas, transmissions, errors = t.load_FGB37()
    >>> plot_transmission_simple(ax, lambdas, transmissions, errors, title="CTIO", label="FGB37")
    >>> lambdas, transmissions, errors = t.load_RG715()
    >>> plot_transmission_simple(ax, lambdas, transmissions, errors, title="CTIO", label="RG715")
    >>> lambdas, transmissions, errors = t.load_telescope_throughput()
    >>> plot_transmission_simple(ax, lambdas, transmissions, errors, title="CTIO", label="Telescope")
    >>> if parameters.DISPLAY: plt.show()
    """
    if uncertainties is None or np.all(np.isclose(uncertainties, np.zeros_like(transmissions))):
        ax.plot(lambdas, transmissions, "-", label=label, lw=lw)
    else:
        ax.errorbar(lambdas, transmissions, yerr=uncertainties, label=label, lw=lw)
    if title != "":
        ax.set_title(title)
    ax.set_xlabel("$\lambda$ [nm]")
    ax.set_ylabel("Transmission")
    ax.set_xlim(parameters.LAMBDA_MIN, parameters.LAMBDA_MAX)
    ax.grid()
    if label != "":
        ax.legend(loc="best")


def plot_all_transmissions(title="Telescope transmissions"):
    """Plot the transmission files.

    Parameters
    ----------
    title: str, optional
        The title of the plot.

    Examples
    --------
    >>> plot_all_transmissions(title="CTIO")

    """

    plt.figure()
    ax = plt.gca()
    t = Throughput()
    lambdas, transmissions, errors = t.load_quantum_efficiency()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="Quantum efficiency")
    lambdas, transmissions, errors = t.load_mirror_reflectivity()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="Mirror")
    lambdas, transmissions, errors = t.load_FGB37()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="FGB37")
    lambdas, transmissions, errors = t.load_RG715()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="RG715")
    lambdas, transmissions, errors = t.load_telescope_throughput()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="Telescope")
    lambdas, transmissions, errors = t.load_total_throughput()
    plot_transmission_simple(ax, lambdas, transmissions, errors, label="Total throughput file",
                             title=title, lw=4)
    if parameters.DISPLAY:
        plt.show()


if __name__ == "__main__":
    import doctest

    doctest.testmod()
