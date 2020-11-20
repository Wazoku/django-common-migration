import os
import sys
from unittest import TestCase, mock

from common_migration.find_common_migrations import (
    MigrationNamesMap,
    MigrationNode,
    build_graph,
    find_reverse_migration_node,
    main,
    parse_migration_dependencies,
    read_migration_data,
    walk_up_nodes,
)


class MigrationNodeTestCase(TestCase):
    def setUp(self):
        self.node = MigrationNode(
            hash=b'2',
            app_name='central',
            name='0002_second',
            dependencies=[
                MigrationNode(
                    hash=b'1',
                    app_name='central',
                    name='0001_first',
                    dependencies=[],
                    dependents=[],
                )
            ],
            dependents=[
                MigrationNode(
                    hash=b'3',
                    app_name='central',
                    name='0003_third',
                    dependencies=[],
                    dependents=[],
                )
            ],
        )

        self.node.dependencies[0].dependents = [self.node]
        self.node.dependents[0].dependencies = [self.node]

    def test_number(self):
        assert self.node.number == 2

    def test_repr(self):
        assert repr(self.node) == (
            "MigrationNode<central/0002_second> -> ('central/0001_first',)"
        )


class BuildGraphTestCase(TestCase):
    def setUp(self):
        self.migration_names: MigrationNamesMap = {
            ('tenancy', '0001_first'): [],
            ('tenancy', '0002_second'): [('tenancy', '0001_first')],
            ('central', '0001_first'): [('tenancy', '0001_first')],
            ('central', '0002_second'): [('central', '0001_first')],
            ('central', '0003_3a'): [('central', '0002_second')],
            ('central', '0003_3b'): [('central', '0002_second')],
            ('central', '0004_merge'): [('central', '0003_3a'), ('central', '0003_3b')],
        }

    def test_build_graph(self):
        latest_node = build_graph('central', self.migration_names)

        assert (latest_node.app_name, latest_node.name) == ('central', '0004_merge')
        assert latest_node.number == 4
        assert latest_node.hash == (
            b'\x9d\xba\xd9\x10\xf6\x8f\xadB\xe2\xad? \xa5\x0cl\x11\xda>\xc3\xcd}\xe6@\x05'
            b'\t\xfc9\xbaI\x8e\xa2\xb6'
        )
        assert [(x.app_name, x.name) for x in latest_node.dependencies] == [
            ('central', '0003_3a'),
            ('central', '0003_3b'),
        ]
        assert [(x.app_name, x.name) for x in latest_node.dependents] == []

        node_three = latest_node.dependencies[0]

        assert node_three.number == 3
        assert node_three.hash == (
            b'0\x9bU+\x18\xd0^?TwAx\x7f\xb0~G\x14?p\t\x95C\xcd\xb4\x0f^m\xe8\xf4\xec\t'
            b'\xdc'
        )
        assert [(x.app_name, x.name) for x in node_three.dependencies] == [
            ('central', '0002_second'),
        ]
        assert [(x.app_name, x.name) for x in node_three.dependents] == [
            ('central', '0004_merge'),
        ]

        node_two = node_three.dependencies[0]

        assert node_two.number == 2
        assert node_two.hash == (
            b'F\x90\xe7\x9f\x8f\x1eq\xfdEu\xcc\xdf\xbeb\x92\xa7\xf77\xd8a\n\xa7\xec.'
            b'\xe1\\\x07+\x07U\xd0\x9c'
        )
        assert [(x.app_name, x.name) for x in node_two.dependencies] == [
            ('central', '0001_first'),
        ]
        assert [(x.app_name, x.name) for x in node_two.dependents] == [
            ('central', '0003_3a'),
            ('central', '0003_3b'),
        ]

        node_one = node_two.dependencies[0]

        assert node_one.number == 1
        assert node_one.hash == (
            b'T\xbf\xf2\xc0i\xf9X\xc10\x0b\xf1N)V\xe5\x11\xeb\xaa\x03\x15\xa7$9\xe1'
            b"\xad]y\x90'\xd6\x0b\xc5"
        )
        assert [(x.app_name, x.name) for x in node_one.dependencies] == [
            ('tenancy', '0001_first'),
        ]
        assert [(x.app_name, x.name) for x in node_one.dependents] == [
            ('central', '0002_second'),
        ]

    def test_build_graph_for_other_app(self):
        latest_node = build_graph('tenancy', self.migration_names)

        assert (latest_node.app_name, latest_node.name) == ('tenancy', '0002_second')
        assert latest_node.number == 2
        assert latest_node.hash == (
            b'\xbd\xeb\x14\x02\x9a\x1f\xd6\x93mQj\xd5\xd3[\xc6\xed\xbb\xf9q\xc4\xe4n"l'
            b'\xb8\xbfD\x1f\xbc!\x05\xd5'
        )

    def test_different_hash_with_missing_nodes(self):
        # Remove one of the migration nodes in the middle.
        del self.migration_names[('central', '0003_3b')]
        self.migration_names[('central', '0004_merge')] = [
            key
            for key in self.migration_names[('central', '0004_merge')]
            if key != ('central', '0003_3b')
        ]

        latest_node = build_graph('central', self.migration_names)

        # We should get a different hash for the latest node, as the graph is different.
        assert latest_node.hash == (
            b'8{o\x85\xe0\x07$\x01\n\x97\x9b\xec5\x0cV\xfc\xd5\xf0\xc6\xcb\xa9:\x16\x0f'
            b'\xfa\x17=\x085F\xce\x91'
        )

        # The hash of the higher node should be the same as the test above.
        # The subgraph is identical.
        node_three = latest_node.dependencies[0]
        assert node_three.hash == (
            b'0\x9bU+\x18\xd0^?TwAx\x7f\xb0~G\x14?p\t\x95C\xcd\xb4\x0f^m\xe8\xf4\xec\t'
            b'\xdc'
        )

    def test_empty_migration_graph(self):
        with self.assertRaises(ValueError) as ctx:
            build_graph('tenancy', {})

        assert str(ctx.exception) == 'No latest/bottom migration found!'

    def test_migration_graph_with_cycles(self):
        migration_names: MigrationNamesMap = {
            ('tenancy', '0001_first'): [('tenancy', '0002_second')],
            ('tenancy', '0002_second'): [('tenancy', '0001_first')],
        }

        with self.assertRaises(ValueError) as ctx:
            build_graph('tenancy', migration_names)

        assert str(ctx.exception) == 'No latest/bottom migration found!'


class WalkUpNodesTestCase(TestCase):
    def test_walk_up_nodes(self):
        migration_names: MigrationNamesMap = {
            ('tenancy', '0001_first'): [],
            ('tenancy', '0002_second'): [('tenancy', '0001_first')],
            ('central', '0001_first'): [('tenancy', '0001_first')],
            ('central', '0002_second'): [('central', '0001_first')],
            ('central', '0003_3a'): [('central', '0002_second')],
            ('central', '0003_3b'): [('central', '0002_second')],
            ('central', '0004_merge'): [('central', '0003_3a'), ('central', '0003_3b')],
        }

        walked_names = [
            (x.app_name, x.name)
            for x in
            walk_up_nodes(build_graph('central', migration_names), 'central')
        ]

        # We should visit the nodes with the highest migration numbers first.
        # We should visit nodes with equal numbers in reverse lexicographic order.
        assert walked_names == [
            ('central', '0004_merge'),
            ('central', '0003_3b'),
            ('central', '0003_3a'),
            ('central', '0002_second'),
            ('central', '0001_first'),
        ]

        tenant_walked_names = [
            (x.app_name, x.name)
            for x in
            walk_up_nodes(build_graph('tenancy', migration_names), 'tenancy')
        ]

        assert tenant_walked_names == [
            ('tenancy', '0002_second'),
            ('tenancy', '0001_first'),
        ]


class FindReverseMigrationNodeTestCase(TestCase):
    def test_find_reverse_with_inserted_migration(self):
        old_map: MigrationNamesMap = {
            ('central', '0001_1'): [],
            ('central', '0002_2'): [('central', '0001_1')],
            ('central', '0003_3'): [('central', '0002_2')],
            ('central', '0004_4'): [('central', '0003_3')],
        }
        new_map: MigrationNamesMap = {
            ('central', '0001_1'): [],
            ('central', '0001_1a'): [('central', '0001_1')],
            ('central', '0002_2'): [('central', '0001_1a')],
            ('central', '0003_3'): [('central', '0002_2')],
            ('central', '0004_4'): [('central', '0003_3')],
        }
        old_node = build_graph('central', old_map)
        new_node = build_graph('central', new_map)

        reverse_node = find_reverse_migration_node(old_node, new_node, 'central')

        assert reverse_node is not None
        assert reverse_node.name == '0001_1'

    def test_find_reverse_migration_with_dead_branches_eliminated(self):
        # We're moving from a branch with more branches and a merge migration.
        old_map: MigrationNamesMap = {
            ('central', '0001_1'): [],
            ('central', '0002_2'): [('central', '0001_1')],
            ('central', '0003_3a'): [('central', '0002_2')],
            ('central', '0003_3b'): [('central', '0002_2')],
            ('central', '0003_3c'): [('central', '0002_2')],
            ('central', '0004_4a'): [('central', '0003_3a')],
            ('central', '0004_4b'): [('central', '0003_3b')],
            ('central', '0004_4c'): [('central', '0003_3c')],
            ('central', '0005_merge'): [
                ('central', '0004_4a'),
                ('central', '0004_4b'),
                ('central', '0004_4c'),
            ],
        }
        # This new branch has just one of the branches. We should search higher up to
        # the common point, so we can reverse the other migrations.
        new_map: MigrationNamesMap = {
            ('central', '0001_1'): [],
            ('central', '0002_2'): [('central', '0001_1')],
            ('central', '0003_3c'): [('central', '0002_2')],
            ('central', '0004_4c'): [('central', '0003_3c')],
        }
        old_node = build_graph('central', old_map)
        new_node = build_graph('central', new_map)

        reverse_node = find_reverse_migration_node(old_node, new_node, 'central')

        assert reverse_node is not None
        assert reverse_node.name == '0002_2'

    def test_find_reverse_for_tenancy_app(self):
        old_map: MigrationNamesMap = {
            ('tenancy', '0001_first'): [],
            ('tenancy', '0002_second'): [('tenancy', '0001_first')],
            ('central', '0001_first'): [('tenancy', '0001_first')],
            ('central', '0002_second'): [('central', '0001_first')],
            ('central', '0003_3a'): [('central', '0002_second')],
            ('central', '0003_3b'): [('central', '0002_second')],
            ('central', '0004_merge'): [('central', '0003_3a'), ('central', '0003_3b')],
            ('tenancy', '0002_third'): [('tenancy', '0002_second')],
        }
        new_map: MigrationNamesMap = {
            ('tenancy', '0001_first'): [],
            ('tenancy', '0002_second'): [('tenancy', '0001_first')],
            ('central', '0001_first'): [('tenancy', '0001_first')],
            ('central', '0002_second'): [('central', '0001_first')],
            ('central', '0003_3a'): [('central', '0002_second')],
            ('central', '0003_3b'): [('central', '0002_second')],
            ('central', '0004_merge'): [('central', '0003_3a'), ('central', '0003_3b')],
            ('tenancy', '0003_new_third'): [('tenancy', '0002_second')],
        }
        old_node = build_graph('tenancy', old_map)
        new_node = build_graph('tenancy', new_map)

        reverse_node = find_reverse_migration_node(old_node, new_node, 'tenancy')

        assert reverse_node is not None
        assert reverse_node.app_name == 'tenancy'
        assert reverse_node.name == '0002_second'


TEST_MIGRATION_FILES_DIR = os.path.join(os.path.dirname(__file__), 'migration_files')


class ReadMigrationDataTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.app_name_list = ['central', 'tenancy']

    def test_read_old_central_migrations(self):
        node = read_migration_data(
            'central',
            self.app_name_list,
            os.path.join(TEST_MIGRATION_FILES_DIR, 'old')
        )

        walked_names = [(x.app_name, x.name) for x in walk_up_nodes(node, 'central')]

        assert walked_names == [
            ('central', '0011_merge'),
            ('central', '0010_make'),
            ('central', '0009_auto'),
            ('central', '0008_remove'),
            ('central', '0008_change'),
            ('central', '0007_merge'),
            ('central', '0007_added'),
            ('central', '0006_copy_pas'),
            ('central', '0006_copy_help'),
            ('central', '0005_add_separate'),
            ('central', '0005_add_dmaic_fields'),
            ('central', '0004_hide'),
            ('central', '0004_add'),
            ('central', '0003_stage_team'),
            ('central', '0003_add_recommendations'),
            ('central', '0002_stage'),
            ('central', '0002_add_ideacopy'),
            ('central', '0001_squashed'),
        ]

        tenant_node = read_migration_data(
            'tenancy',
            self.app_name_list,
            os.path.join(TEST_MIGRATION_FILES_DIR, 'old')
        )

        walked_tenant_names = [
            (x.app_name, x.name) for x in walk_up_nodes(tenant_node, 'tenancy')
        ]

        # There's an initial migration in the directory, and we should use the newer
        # squashed migration as the root instead.
        assert walked_tenant_names == [
            ('tenancy', '0011_enable'),
            ('tenancy', '0010_enable'),
            ('tenancy', '0009_add'),
            ('tenancy', '0008_rename'),
            ('tenancy', '0007_client_features'),
            ('tenancy', '0006_client_repository_images'),
            ('tenancy', '0005_client_moderation'),
            ('tenancy', '0004_client_require'),
            ('tenancy', '0003_client_session'),
            ('tenancy', '0002_client_site'),
            ('tenancy', '0001_squashed'),
        ]


class ParseMigrationDepenciesTestCase(TestCase):
    def test_parse_empty_python_file(self):
        filename = os.path.join(TEST_MIGRATION_FILES_DIR, 'empty_file.py')

        with self.assertRaises(SyntaxError) as ctx:
            parse_migration_dependencies(filename, ['central', 'tenancy'])

        assert str(ctx.exception) == (
            f'Migration class is missing for migration: {filename}'
        )

    def test_parse_file_with_invalid_dependency(self):
        filename = os.path.join(TEST_MIGRATION_FILES_DIR, 'invalid_dependency.py')

        with self.assertRaises(ValueError) as ctx:
            parse_migration_dependencies(filename, ['central', 'tenancy'])

        assert str(ctx.exception) == (
            f'Invalid tuple for `dependencies`: {filename}'
        )

    def test_parse_file_with_invalid_replacments(self):
        filename = os.path.join(TEST_MIGRATION_FILES_DIR, 'invalid_replacements.py')

        with self.assertRaises(ValueError) as ctx:
            parse_migration_dependencies(filename, ['central', 'tenancy'])

        assert str(ctx.exception) == (
            f'Invalid tuple for `replaces`: {filename}'
        )

    def test_parse_file_with_dependency_not_as_tuple(self):
        filename = os.path.join(TEST_MIGRATION_FILES_DIR, 'dependency_not_tuple.py')

        with self.assertRaises(TypeError) as ctx:
            parse_migration_dependencies(filename, ['central', 'tenancy'])

        assert str(ctx.exception) == (
            f'Value is not tuple for `dependencies`: {filename}'
        )


# This test runs the whole script to make sure it returns the right output.
class FindMigrationScriptTestCase(TestCase):
    def setUp(self):
        super().setUp()

        self.__argv = sys.argv
        sys.argv = [
            'find_common_migrations.py',
            '--all-names',
            'central,tenancy',
            '--app-name',
            'central',
            os.path.join(TEST_MIGRATION_FILES_DIR, 'old'),
            os.path.join(TEST_MIGRATION_FILES_DIR, 'new'),
        ]

    def tearDown(self):
        sys.argv = self.__argv

        super().tearDown()

    def test_find_central_reverse_migration(self):
        with mock.patch('builtins.print') as print_mock:
            main()

        # The old migration files have 0005_add_dmaic... pointing this migration file,
        # but not the new files.
        #
        # The new files have 0007_merge... to merge migrations which point to this
        # migration file and also the other migratino files up to tree.
        #
        # Reverting back to this migration will result in unapply the "merge" migration
        # file, then migrating forwards to it an on to 0010_make...
        print_mock.assert_called()
        print_mock.assert_has_calls([
            mock.call('0004_add'),
        ])

    def test_find_tenancy_reverse_migration(self):
        sys.argv[4] = 'tenancy'

        with mock.patch('builtins.print') as print_mock:
            main()

        print_mock.assert_called()
        print_mock.assert_has_calls([
            mock.call('0010_enable'),
        ])

    def test_invalid_app_name(self):
        sys.argv[4] = 'wat'

        with self.assertRaises(SystemExit) as ctx:
            main()

        assert str(ctx.exception) == 'Invalid app_name: wat'

    def test_script_fails_when_all_migrations_are_replaced(self):
        sys.argv[-1] = os.path.join(TEST_MIGRATION_FILES_DIR, 'totally_replaced')

        with self.assertRaises(SystemExit) as ctx:
            main()

        assert str(ctx.exception) == 'There are no migrations in common!'
