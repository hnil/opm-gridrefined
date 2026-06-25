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
#include <config.h>

#include <opm/grid/cpgrid/AdaptiveCpGrid.hpp>

#include <opm/grid/cpgrid/refinement/ConformingBlockBuilder.hpp>
#include <opm/grid/cpgrid/refinement/RefinementBuilder.hpp>
#include <opm/grid/cpgpreprocess/preprocess.h>

#include <memory>
#include <stdexcept>
#include <string>
#include <utility>

namespace Opm
{

AdaptiveCpGrid::AdaptiveCpGrid(const std::array<int,3>& dims,
                               std::vector<double> coord,
                               std::vector<double> zcorn,
                               std::vector<int> actnum)
    : dims_(dims)
    , coord_(std::move(coord))
    , zcorn_(std::move(zcorn))
    , actnum_(std::move(actnum))
{
    // Build the coarse (level-zero) leaf from the macro corner-point input.
    grdecl g{};
    g.dims[0] = dims_[0];
    g.dims[1] = dims_[1];
    g.dims[2] = dims_[2];
    g.coord  = coord_.data();
    g.zcorn  = zcorn_.data();
    g.actnum = actnum_.empty() ? nullptr : actnum_.data();
    grid_.processEclipseFormat(g, false);
}

void AdaptiveCpGrid::markBox(const std::array<int,3>& startIJK,
                             const std::array<int,3>& endIJK,
                             const std::array<int,3>& cellsPerDim,
                             const std::string& name)
{
    Refinement::BlockRefinement r;
    r.name = name.empty() ? ("ADAPT" + std::to_string(marks_.size() + 1)) : name;
    r.parentGridName = "GLOBAL";
    r.cellsPerDim = cellsPerDim;
    r.startIJK = startIJK;
    r.endIJK = endIJK;
    marks_.push_back(std::move(r));
}

void AdaptiveCpGrid::markCell(const std::array<int,3>& ijk,
                              const std::array<int,3>& cellsPerDim)
{
    markBox(ijk, {ijk[0] + 1, ijk[1] + 1, ijk[2] + 1}, cellsPerDim);
}

void AdaptiveCpGrid::adapt()
{
    if (marks_.empty()) {
        return;
    }
    if (grid_.maxLevel() > 0) {
        throw std::runtime_error(
            "AdaptiveCpGrid::adapt: the grid is already refined. Re-adapt of an "
            "already-refined grid is not implemented yet (this first cut refines "
            "level zero once via the full-rebuild oracle). Reconstruct the "
            "AdaptiveCpGrid to refine a different region.");
    }

    // Drive the same conforming refinement builder the static CARFIN path uses.
    // Register it for the duration of the addLgrsUpdateLeafView call, then
    // restore whatever was registered before (RAII-style, exception-safe).
    auto previous = Refinement::setBuilder(
        std::make_unique<Refinement::ConformingBlockBuilder>(
            dims_, coord_, zcorn_, actnum_));

    std::vector<std::array<int,3>> cellsPerDim;
    std::vector<std::array<int,3>> startIJK;
    std::vector<std::array<int,3>> endIJK;
    std::vector<std::string>       names;
    cellsPerDim.reserve(marks_.size());
    startIJK.reserve(marks_.size());
    endIJK.reserve(marks_.size());
    names.reserve(marks_.size());
    for (const auto& m : marks_) {
        cellsPerDim.push_back(m.cellsPerDim);
        startIJK.push_back(m.startIJK);
        endIJK.push_back(m.endIJK);
        names.push_back(m.name);
    }

    try {
        // Same entry point as the static CARFIN path; the only difference is that
        // the boxes come from marks here, not from a deck CARFIN keyword.
        grid_.addLgrsUpdateLeafView(cellsPerDim, startIJK, endIJK, names);
    }
    catch (...) {
        Refinement::setBuilder(std::move(previous));
        throw;
    }
    Refinement::setBuilder(std::move(previous));

    marks_.clear();
}

} // namespace Opm
