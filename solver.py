"""Breach Protocol solver for Cyberpunk 2077.

Finds the optimal path through the code matrix that satisfies
as many target sequences as possible within the buffer limit.

Rules:
- Start by picking any cell in row 0 (orientation: row → pick column)
- Then locked to that column (orientation: column → pick row)
- Alternates row/column each step
- Each cell can only be used once
- Path length limited by buffer size
"""

from itertools import product


def solve(matrix, sequences, buffer_size):
    """Find the best path through the matrix matching target sequences.

    Args:
        matrix: 2D list of hex strings, e.g. [["55","1C","BD"],...]
        sequences: list of lists, e.g. [["55","1C","E9"], ["BD","BD","FF","55"]]
        buffer_size: max number of cells to visit

    Returns:
        dict with:
            path: list of (row, col) tuples
            values: list of hex strings along the path
            matched: list of booleans per sequence
            score: number of sequences matched
    """
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0
    best = {"path": [], "values": [], "matched": [False] * len(sequences), "score": -1}

    def check_sequences(values):
        """Check which sequences are matched by the current path values."""
        val_str = " ".join(values)
        matched = []
        for seq in sequences:
            seq_str = " ".join(seq)
            matched.append(seq_str in val_str)
        return matched

    def dfs(path, values, visited, is_row, fixed_idx, depth):
        nonlocal best

        # Evaluate current path
        if len(values) > 0:
            matched = check_sequences(values)
            score = sum(matched)
            # Prefer paths that match more sequences; break ties by shorter path
            if score > best["score"] or (score == best["score"] and len(path) < len(best["path"])):
                best = {
                    "path": list(path),
                    "values": list(values),
                    "matched": matched,
                    "score": score,
                }
            # Early exit if all sequences matched
            if score == len(sequences):
                return True

        # Stop if buffer full
        if depth >= buffer_size:
            return False

        # Generate next moves
        if is_row:
            # Pick any column in the fixed row
            for c in range(cols):
                if (fixed_idx, c) not in visited:
                    visited.add((fixed_idx, c))
                    path.append((fixed_idx, c))
                    values.append(matrix[fixed_idx][c])
                    if dfs(path, values, visited, False, c, depth + 1):
                        return True
                    values.pop()
                    path.pop()
                    visited.remove((fixed_idx, c))
        else:
            # Pick any row in the fixed column
            for r in range(rows):
                if (r, fixed_idx) not in visited:
                    visited.add((r, fixed_idx))
                    path.append((r, fixed_idx))
                    values.append(matrix[r][fixed_idx])
                    if dfs(path, values, visited, True, r, depth + 1):
                        return True
                    values.pop()
                    path.pop()
                    visited.remove((r, fixed_idx))

        return False

    # Try starting from each cell in row 0
    for c in range(cols):
        visited = {(0, c)}
        found = dfs(
            [(0, c)],
            [matrix[0][c]],
            visited,
            False,  # After picking from row, next is column-locked
            c,      # Locked to column c
            1,
        )
        if found:
            break

    return best


def solve_best_effort(matrix, sequences, buffer_size):
    """Try all possible orderings and combinations to find the best solution.

    Tries solving with all sequences, then subsets, to maximize matches.
    """
    rows = len(matrix)
    cols = len(matrix[0]) if rows else 0

    if not sequences:
        return {"path": [], "values": [], "matched": [], "score": 0}

    # First try: solve with all sequences
    result = solve(matrix, sequences, buffer_size)

    # If we matched everything, done
    if result["score"] == len(sequences):
        return result

    # Try different orderings of sequences to find better paths
    # The order matters because subsequence matching is positional
    best_result = result

    # For small number of sequences, try permutations
    if len(sequences) <= 4:
        from itertools import permutations
        for perm in permutations(range(len(sequences))):
            reordered = [sequences[i] for i in perm]
            r = solve(matrix, reordered, buffer_size)
            if r["score"] > best_result["score"]:
                # Map matched back to original order
                matched_orig = [False] * len(sequences)
                for idx, m in enumerate(r["matched"]):
                    if m:
                        matched_orig[perm[idx]] = True
                best_result = {
                    "path": r["path"],
                    "values": r["values"],
                    "matched": matched_orig,
                    "score": r["score"],
                }
            if best_result["score"] == len(sequences):
                break

    return best_result


if __name__ == "__main__":
    # Test with the user's actual breach protocol screenshot
    matrix = [
        ["55", "1C", "BD", "55", "BD", "E9"],
        ["55", "BD", "E9", "1C", "1C", "1C"],
        ["E9", "FF", "55", "E9", "55", "55"],
        ["1C", "1C", "BD", "55", "E9", "FF"],
        ["55", "FF", "55", "BD", "1C", "E9"],
        ["E9", "E9", "1C", "FF", "BD", "BD"],
    ]
    sequences = [
        ["55", "1C", "E9"],      # NEUTRALIZE MALWARE
        ["BD", "BD", "FF", "55"],  # DATAMINE: COPY MALWARE
    ]
    buffer_size = 7  # From screenshot buffer slots

    result = solve_best_effort(matrix, sequences, buffer_size)
    print(f"Score: {result['score']}/{len(sequences)}")
    print(f"Path: {result['path']}")
    print(f"Values: {' '.join(result['values'])}")
    print(f"Matched: {result['matched']}")
    for i, (r, c) in enumerate(result["path"]):
        print(f"  Step {i+1}: Row {r}, Col {c} -> {matrix[r][c]}")
