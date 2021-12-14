#!/usr/bin/env python3

"""
Find a common migration node between two versions of Django code.

"""

import argparse
import ast
import hashlib
import os
import re
import sys
from typing import Dict, Iterator, List, Optional, Set, Tuple, cast

MIGRATION_NAME_RE = re.compile(r'^\d+_.')


class NotAMigrationError(IOError):
    pass


class MigrationNode:
    """
    A migration node, with the following attributes.

    hash:         A hash describing the entire subgraph up from the node.
    app_name:     The app name of the migration.
    name:         The name of the migration.
    dependencies: The dependencies for this migration node.
    dependents:   Nodes that depend on this node.
    """

    number: int

    def __init__(
        self,
        *,
        hash: bytes,
        app_name: str,
        name: str,
        dependencies: 'List[MigrationNode]',
        dependents: 'List[MigrationNode]',
    ):
        self.hash = hash
        self.app_name = app_name
        self.name = name
        self.dependencies = dependencies
        self.dependents = dependents

        split_name = name.split('_', 1)

        self.number = int(split_name[0])

    @property
    def path(self):
        return f'{self.app_name}/{self.name}'

    def __repr__(self):
        # Return a representation printing the node and its dependencies.
        return (
            f'MigrationNode<{self.path}> -> '
            + str(tuple(x.path for x in self.dependencies))
        )


def walk_up_nodes(
    bottom_node: MigrationNode,
    app_name: str,
) -> Iterator[MigrationNode]:
    """
    Starting from the latest migration node, walk up the graph of migrations,
    yielding all migration nodes with the given `app_name`.

    Nodes will only be explored at most once.
    """
    explored_set = {bottom_node.hash}
    heap = [bottom_node]

    while heap:
        node = heap.pop()

        yield node

        # Add any dependencies to the list to explore.
        # We will not add nodes we've already added.
        for dependency in node.dependencies:
            if dependency.app_name == app_name and dependency.hash not in explored_set:
                explored_set.add(dependency.hash)
                heap.append(dependency)

        # Sort the new nodes to explore.
        # We will keep putting the highest number migrations on the end, and
        # explore migrations from the highest to lowest.
        heap.sort(key=lambda node: (node.number, node.name))


def find_lowest_common_ancestor(
    old_branch_node: MigrationNode,
    new_branch_node: MigrationNode,
    app_name: str,
) -> Optional[MigrationNode]:
    """
    Find the lowest common ancestor in the two graphs, in the given app.
    """
    new_node_hash_set = {
        node.hash
        for node in walk_up_nodes(new_branch_node, app_name)
    }

    for node in walk_up_nodes(old_branch_node, app_name):
        if node.hash in new_node_hash_set:
            return node

    # Return `None` if we can't find anything in common.
    return None


def eliminate_dead_branches(
    lca_node: MigrationNode,
    app_name: str,
) -> MigrationNode:
    """
    Improve the choice of the common migration node by exhaustively walking up
    nodes until we find the lowest migration node without branches of migration
    nodes that don't exist in the new version of the code.
    """
    # Mark all of the nodes we can find walking up all the way to the root.
    marked_set = {node.hash for node in walk_up_nodes(lca_node, app_name)}
    selected_node = lca_node

    # Sweep all nodes away lower than the lowest node that dead branches will
    # dangle off of.
    for node in walk_up_nodes(lca_node, app_name):
        if any(
            dependent.hash not in marked_set
            for dependent in node.dependents
            if dependent.app_name == app_name
        ):
            selected_node = node

    return selected_node


def find_reverse_migration_node(
    old_branch_node: MigrationNode,
    new_branch_node: MigrationNode,
    app_name: str,
) -> Optional[MigrationNode]:
    """
    Given migration nodes that start from the latest migration and point to the
    earliest migration for two branches, and an app we're interested in
    migrating, work out the migration we need to revert back to.
    """
    lca_node = find_lowest_common_ancestor(
        old_branch_node,
        new_branch_node,
        app_name,
    )

    if lca_node is None:
        return None

    return eliminate_dead_branches(lca_node, app_name)


def parse_migration_name(filename: str) -> Optional[str]:
    """
    Given a possible migration filename, return either the name of the
    migration, or ``None`` if the filename is not a migration file.
    """
    migration_name = os.path.splitext(os.path.basename(filename))[0]

    if not MIGRATION_NAME_RE.match(migration_name):
        return None

    return migration_name


def _read_migration_tuples(
    *,
    filename: str,
    app_name_list: List[str],
    class_node: ast.ClassDef,
    attribute_name: str,
) -> List[Tuple[str, str]]:
    ast_list = next(
        (
            node.value
            for node in class_node.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == attribute_name
            and isinstance(node.value, ast.List)
        ),
        None
    )

    if ast_list is None:
        return []

    migration_names: list[tuple[str, str]] = []

    for element in ast_list.elts:
        if not isinstance(element, ast.Tuple):
            raise TypeError(f'Value is not tuple for `{attribute_name}`: {filename}')

        possible_pair = tuple(
            node.s
            for node in element.elts
            if isinstance(node, ast.Str)
        )

        if len(possible_pair) != 2:
            raise ValueError(f'Invalid tuple for `{attribute_name}`: {filename}')

        # Only consider values in the apps we care about.
        if possible_pair[0] in app_name_list:
            migration_names.append(cast(Tuple[str, str], possible_pair))

    return migration_names


def parse_migration_dependencies(
    filename: str,
    app_name_list: List[str],
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """
    Given a migration filename, return a pair of the migration name and
    dependencies for the migration.
    """
    with open(filename) as migration_file:
        parsed = ast.parse(migration_file.read())

    class_node = next(
        (
            node
            for node in parsed.body
            if isinstance(node, ast.ClassDef)
            and any(
                base.attr == 'Migration'
                for base in node.bases
                if isinstance(base, ast.Attribute)
            )
        ),
        None
    )

    if class_node is None:
        raise SyntaxError(
            f'Migration class is missing for migration: {filename}'
        )

    dependencies = _read_migration_tuples(
        filename=filename,
        app_name_list=app_name_list,
        class_node=class_node,
        attribute_name='dependencies',
    )
    replaces = _read_migration_tuples(
        filename=filename,
        app_name_list=app_name_list,
        class_node=class_node,
        attribute_name='replaces',
    )

    return dependencies, replaces


def hash_node(node: MigrationNode, app_name: str) -> bytes:
    """
    Given any migration node, walk all the way up the tree for a given app and
    produce a unique hash value that identifies the subgraph from the given
    migration node.
    """
    app_migration_set = {
        (current_node.app_name, current_node.name)
        for current_node in
        walk_up_nodes(node, app_name)
    }

    combined_string = ' '.join(
        string
        for key in sorted(app_migration_set)
        for string in key
    )

    return (
        hashlib.sha256(combined_string.encode('utf-8'))
        .digest()
    )


MigrationNamesMap = Dict[Tuple[str, str], List[Tuple[str, str]]]


def create_migration_maps(
    app_name_list: List[str],
    project_dir: str,
) -> MigrationNamesMap:
    """
    Given the name of an app and a directory for Django project code, read
    all of the migration dependencies into a map.
    """
    # A map from a migration to its dependencies.
    raw_migrations: MigrationNamesMap = {}
    replaced_migrations: Set[Tuple[str, str]] = set()

    for app_name in app_name_list:
        migration_dir = os.path.join(project_dir, app_name, 'migrations')

        # Look at all files from the highest to the lowest.
        # We will later eliminate migrations replaced by squashed migration files.
        for base_filename in sorted(os.listdir(migration_dir), reverse=True):
            filename = os.path.join(migration_dir, base_filename)

            migration_name = parse_migration_name(filename)

            if migration_name is not None:
                dependecies, replaces = parse_migration_dependencies(
                    filename,
                    app_name_list,
                )
                replaced_migrations.update(replaces)

                raw_migrations[(app_name, migration_name)] = dependecies

    # Remove all migrations that have been replaced by squashed migrations.
    for dead_migration in replaced_migrations:
        raw_migrations.pop(dead_migration, None)

    return raw_migrations


def build_graph(
    app_name: str,
    raw_migrations: MigrationNamesMap,
) -> MigrationNode:
    """
    Given an app name and a map of migrations, build a graph starting from the
    bottom node with dependencies and dependents.
    """
    # Build a map referencing everything in reverse.
    reverse_migrations: MigrationNamesMap = {}

    for key, value in raw_migrations.items():
        for reverse_key in value:
            reverse_migrations.setdefault(reverse_key, []).append(key)

    node_map: Dict[Tuple[str, str], MigrationNode] = {
        key: MigrationNode(
            hash=b'',
            app_name=key[0],
            name=key[1],
            dependencies=[],
            dependents=[],
        )
        for key in raw_migrations
    }

    latest_node: Optional[MigrationNode] = None

    # Set up dependencies.
    for node in node_map.values():
        node.dependencies = [
            node_map[key]
            for key in
            raw_migrations[(node.app_name, node.name)]
        ]

        dependent_keys = reverse_migrations.get((node.app_name, node.name))

        if dependent_keys is not None:
            node.dependents = [node_map[key] for key in dependent_keys]

        if (
            node.app_name == app_name
            and not any(x.app_name == app_name for x in node.dependents)
        ):
            # The node without any dependents is the latest migration.
            latest_node = node

    for node in node_map.values():
        if node.app_name == app_name:
            node.hash = hash_node(node, app_name)

    if latest_node is None:
        raise ValueError('No latest/bottom migration found!')

    return latest_node


def read_migration_data(
    app_name: str,
    app_name_list: List[str],
    project_dir: str,
) -> MigrationNode:
    """
    Given a list of app names and a directory with Djanngo project code, read
    all of the migration files into a graph.
    """
    return build_graph(
        app_name,
        create_migration_maps(app_name_list, project_dir)
    )


def parse_arguments() -> Tuple[List[str], str, str, str]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--all-names',
        help='Comma-separated app names to check',
        required=True,
    )
    parser.add_argument(
        '--app-name',
        help='The app name, e.g. "central"',
        required=True,
    )
    parser.add_argument('old_code', help='Old project directory')
    parser.add_argument('new_code', help='New project directory')

    args = parser.parse_args()

    return (
        args.all_names.split(','),
        args.app_name,
        args.old_code,
        args.new_code
    )


def main():
    app_name_list, app_name, old_dir, new_dir = parse_arguments()

    if app_name not in app_name_list:
        sys.exit('Invalid app_name: ' + app_name)

    old_node = read_migration_data(app_name, app_name_list, os.path.expanduser(old_dir))
    new_node = read_migration_data(app_name, app_name_list, os.path.expanduser(new_dir))

    reverse_node = find_reverse_migration_node(old_node, new_node, app_name)

    if reverse_node is not None:
        print(f'{reverse_node.name}')


if __name__ == "__main__":  # pragma: no cover
    main()
