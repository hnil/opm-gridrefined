/*
  Copyright 2026 SINTEF Digital.

  This file is part of the Open Porous Media project (OPM).

  OPM is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  OPM is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with OPM.  If not, see <http://www.gnu.org/licenses/>.
*/
//! \file
//! \brief Micro-benchmark for AdaptiveCpGrid: time the coarse build, the
//!        (static-equivalent) refinement, and iteration/lookup over the refined
//!        leaf. A CpGrid-only reference for now (OPM's ALUGrid has no in-sim LGR
//!        refinement to compare against). Prints timings; always passes.
#include <config.h>

#define BOOST_TEST_MODULE AdaptiveCpGridBench
#include <boost/test/unit_test.hpp>

#include <opm/grid/CpGrid.hpp>
#include <opm/grid/cpgrid/AdaptiveCpGrid.hpp>
#include <opm/grid/cpgrid/refinement/ConformingBlockBuilder.hpp>
#include <opm/grid/cpgrid/refinement/RefinementBuilder.hpp>
#include <opm/grid/cpgpreprocess/preprocess.h>

#include <dune/common/parallel/mpihelper.hh>
#include <dune/grid/common/mcmgmapper.hh>

#include <memory>

#include <algorithm>
#include <array>
#include <chrono>
#include <iostream>
#include <vector>

namespace {

using Clock = std::chrono::steady_clock;
double msOf(Clock::time_point a, Clock::time_point b)
{ return std::chrono::duration<double, std::milli>(b - a).count(); }

struct MPIFixture {
    MPIFixture() {
        auto& argv = boost::unit_test::framework::master_test_suite().argv;
        auto& argc = boost::unit_test::framework::master_test_suite().argc;
        Dune::MPIHelper::instance(argc, argv);
    }
};

// Uniform Cartesian macro grid (unit cells), expressed as COORD/ZCORN.
void makeCartesian(int nx, int ny, int nz,
                   std::vector<double>& coord, std::vector<double>& zcorn)
{
    coord.resize(6 * (nx + 1) * (ny + 1));
    for (int j = 0; j <= ny; ++j)
        for (int i = 0; i <= nx; ++i) {
            double* p = &coord[6 * (static_cast<std::size_t>(j) * (nx + 1) + i)];
            p[0] = i; p[1] = j; p[2] = 0.0;
            p[3] = i; p[4] = j; p[5] = nz;
        }
    zcorn.resize(8 * static_cast<std::size_t>(nx) * ny * nz);
    for (int k = 0; k < 2 * nz; ++k)
        for (int j = 0; j < 2 * ny; ++j)
            for (int i = 0; i < 2 * nx; ++i)
                zcorn[static_cast<std::size_t>(i) + 2 * static_cast<std::size_t>(nx) * j
                      + 4 * static_cast<std::size_t>(nx) * ny * k] = 0.5 * (k + 1);
}

// "First-level LGR" refinement exactly as flow's static CARFIN path does it:
// build the coarse grid, then addLgrsUpdateLeafView (register the conforming
// builder + refine). Returns the refinement time in ms (coarse build excluded).
double timeStaticLgrRefine(int nx, int ny, int nz, int fac)
{
    std::vector<double> coord, zcorn;
    makeCartesian(nx, ny, nz, coord, zcorn);
    Dune::CpGrid grid;
    grdecl g{};
    g.dims[0] = nx; g.dims[1] = ny; g.dims[2] = nz;
    g.coord = coord.data(); g.zcorn = zcorn.data(); g.actnum = nullptr;
    grid.processEclipseFormat(g, false);

    auto a = Clock::now();
    auto prev = Opm::Refinement::setBuilder(
        std::make_unique<Opm::Refinement::ConformingBlockBuilder>(
            std::array<int,3>{nx, ny, nz}, coord, zcorn, std::vector<int>{}));
    grid.addLgrsUpdateLeafView({{fac,fac,fac}}, {{0,0,0}}, {{nx,ny,nz}}, {"LGR1"});
    auto b = Clock::now();
    Opm::Refinement::setBuilder(std::move(prev));
    return msOf(a, b);
}

void runBench(int nx, int ny, int nz, int fac)
{
    std::vector<double> coord, zcorn;
    makeCartesian(nx, ny, nz, coord, zcorn);
    const long coarse = static_cast<long>(nx) * ny * nz;

    // best-of-3 for both refinement paths
    double staticMs = 1e30, adaptMs = 1e30;
    for (int rep = 0; rep < 3; ++rep)
        staticMs = std::min(staticMs, timeStaticLgrRefine(nx, ny, nz, fac));

    auto t0 = Clock::now();
    Opm::AdaptiveCpGrid grid({nx, ny, nz}, coord, zcorn, {});
    auto t1 = Clock::now();
    grid.markBox({0,0,0}, {nx,ny,nz}, {fac,fac,fac});  // refine whole grid
    auto t2 = Clock::now();
    grid.adapt();
    auto t3 = Clock::now();
    adaptMs = msOf(t2, t3);

    const auto leaf = grid.grid().leafGridView();
    const long leafCells = grid.grid().size(0);

    auto t4 = Clock::now();
    double vol = 0.0;
    for (const auto& e : Dune::elements(leaf)) vol += e.geometry().volume();
    auto t5 = Clock::now();

    Dune::MultipleCodimMultipleGeomTypeMapper<std::decay_t<decltype(leaf)>>
        mapper(leaf, Dune::mcmgElementLayout());
    auto t6 = Clock::now();
    long checksum = 0;
    for (const auto& e : Dune::elements(leaf)) checksum += mapper.index(e);
    auto t7 = Clock::now();

    std::cout << "\n=== AdaptiveCpGrid bench " << nx << "x" << ny << "x" << nz
              << " refine whole grid x" << fac << "/dir ===\n"
              << "  coarse cells        : " << coarse << "\n"
              << "  leaf cells          : " << leafCells
              << "  (x" << (double)leafCells / coarse << ")\n"
              << "  coarse build        : " << msOf(t0, t1) << " ms\n"
              << "  REFINE static LGR   : " << staticMs << " ms  ("
              << leafCells / (staticMs * 1e3) << " M leaf-cells/s)\n"
              << "  REFINE adaptive     : " << adaptMs << " ms  ("
              << leafCells / (adaptMs * 1e3) << " M leaf-cells/s)"
              << "   [adaptive/static = " << adaptMs / staticMs << "x]\n"
              << "  leaf iterate+geom   : " << msOf(t4, t5) << " ms  ("
              << leafCells / (msOf(t4, t5) * 1e3) << " M cells/s)\n"
              << "  leaf index lookup   : " << msOf(t6, t7) << " ms  ("
              << leafCells / (msOf(t6, t7) * 1e3) << " M cells/s)\n"
              << "  (vol=" << vol << " chk=" << checksum << ")\n";
    BOOST_CHECK_GT(leafCells, coarse);
}

} // namespace

BOOST_GLOBAL_FIXTURE(MPIFixture);

BOOST_AUTO_TEST_CASE(benchmark)
{
    runBench(40, 40, 10, 2);    // 16k -> ~128k
    runBench(60, 60, 20, 2);    // 72k -> ~576k
    runBench(40, 40, 10, 3);    // 16k -> ~432k (x27/cell)
}
