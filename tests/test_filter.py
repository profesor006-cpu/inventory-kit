#Pruebas automáticas de Filter
import unittest
from inventorykit.query import Filter
from inventorykit.exceptions import InvalidFilterError


#Casos validos
class TestFilterValid(unittest.TestCase):
    def test_empty_filter_is_valid(self):
        #Un filtro esta vacio si no tiene condiciones
        self.assertEqual(Filter({}).to_dict(), {})

    def test_short_equality_is_normalized_to_eq(self):
        self.assertEqual(Filter({"category": "Tornillos"}).to_dict(), {"category": {"$eq": "Tornillos"}})

    def test_eq_none_is_valid(self):
        self.assertEqual(Filter({"description": None}).to_dict(), {"description": {"$eq": None}})

    def test_all_comparison_operators(self):
        #Los probamos con un valor numerico
        for op in ("$eq", "$ne", "$gt", "$gte", "$lt", "$lte"):
            with self.subTest(op=op):
                self.assertEqual(Filter({"stock": {op: 5}}).to_dict(), {"stock": {op: 5}})

    def test_ordering_accepts_strings_and_floats(self):
        Filter({"timestamp": {"$gte": "2026-01-01T00:00:00+00:00"}})
        Filter({"attributes.unit_cost": {"$lt": 12.5}})

    def test_membership_operators(self):
        self.assertEqual(Filter({"category": {"$in": ["A", "B"]}}).to_dict(), {"category": {"$in": ["A", "B"]}})
        self.assertEqual(Filter({"id": {"$nin": ["X1"]}}).to_dict(), {"id": {"$nin": ["X1"]}})

    def test_exists_and_contains(self):
        self.assertEqual(Filter({"attributes.brand": {"$exists": True}}).to_dict(), {"attributes.brand": {"$exists": True}})
        self.assertEqual(Filter({"name": {"$contains": "torn"}}).to_dict(), {"name": {"$contains": "torn"}})

    def test_multiple_operators_on_one_field(self):
        conditions = {"stock": {"$gte": 1, "$lte": 10}}
        self.assertEqual(Filter(conditions).to_dict(), conditions)

    def test_multiple_fields_are_kept(self):
        result = Filter({"category": "A", "stock": {"$gt": 0}}).to_dict()
        self.assertEqual(result, {"category": {"$eq": "A"}, "stock": {"$gt": 0}})

    def test_logical_operators_and_nesting(self):
        f = Filter({"$and": [{"category": "A"}, {"$or": [{"stock": {"$lt": 3}}, {"name": {"$contains": "x"}}]}]})
        self.assertEqual(f.to_dict(), {"$and": [ {"category": {"$eq": "A"}}, {"$or": [{"stock": {"$lt": 3}}, {"name": {"$contains": "x"}}]}]})

    def test_logical_mixed_with_fields(self):
        f = Filter({"active": True, "$or": [{"category": "A"}, {"category": "B"}]})
        self.assertIn("$or", f.to_dict())
        self.assertEqual(f.to_dict()["active"], {"$eq": True})


#Casos invalidos
class TestFilterInvalid(unittest.TestCase):
    def assertInvalid(self, conditions):
        #Comprueba que se lance InvalidFilterError
        with self.assertRaises(InvalidFilterError):
            Filter(conditions)

    def test_conditions_must_be_dict(self):
        for bad in (None, [], "x", 5, [("a", 1)]):
            with self.subTest(bad=bad):
                self.assertInvalid(bad)

    def test_bad_keys(self):
        self.assertInvalid({"": 1})
        self.assertInvalid({"   ": 1})
        self.assertInvalid({1: 1})

    def test_unknown_operator(self):
        self.assertInvalid({"stock": {"$regex": "a"}})
        self.assertInvalid({"$foo": 1})

    def test_operator_without_field(self):
        self.assertInvalid({"$gt": 5})

    def test_mixed_operators_and_plain_keys(self):
        self.assertInvalid({"stock": {"$gt": 1, "min": 2}})

    def test_empty_operator_dict(self):
        self.assertInvalid({"stock": {}})

    def test_logical_inside_field(self):
        self.assertInvalid({"stock": {"$and": [{"a": 1}]}})

    def test_logical_needs_non_empty_list_of_dicts(self):
        self.assertInvalid({"$and": []})
        self.assertInvalid({"$or": {"a": 1}})
        self.assertInvalid({"$or": [1, 2]})
        self.assertInvalid({"$and": [{"a": {"$bad": 1}}]})

    def test_membership_needs_non_empty_list(self):
        self.assertInvalid({"id": {"$in": "A"}})
        self.assertInvalid({"id": {"$in": []}})
        self.assertInvalid({"id": {"$nin": ("A", "B")}})
        self.assertInvalid({"id": {"$in": [None]}})
        self.assertInvalid({"id": {"$in": [["A"]]}})

    def test_ordering_rejects_bad_operands(self):
        for bad in (None, True, [1], {"a": 1}, float("nan"), float("inf")):
            with self.subTest(bad=bad):
                self.assertInvalid({"stock": {"$gt": bad}})

    def test_equality_rejects_containers(self):
        self.assertInvalid({"name": ["a", "b"]})
        self.assertInvalid({"name": {"$eq": ["a"]}})
        self.assertInvalid({"name": {"$ne": {"a": 1}}})
        self.assertInvalid({"stock": float("nan")})

    def test_exists_needs_bool(self):
        self.assertInvalid({"attributes.x": {"$exists": 1}})
        self.assertInvalid({"attributes.x": {"$exists": "true"}})

    def test_contains_needs_non_empty_string(self):
        self.assertInvalid({"name": {"$contains": ""}})
        self.assertInvalid({"name": {"$contains": 5}})

    def test_invalid_filter_error_is_value_error(self):
        with self.assertRaises(ValueError):
            Filter({"$gt": 1})


class TestFilterIsolation(unittest.TestCase):
    def test_to_dict_returns_independent_copy(self):
        f = Filter({"id": {"$in": ["A", "B"]}})
        copy_ = f.to_dict()
        copy_["id"]["$in"].append("C")
        copy_["extra"] = 1
        #Modificar la copia no cambia el filtro original
        self.assertEqual(f.to_dict(), {"id": {"$in": ["A", "B"]}})

    def test_filter_does_not_share_input_objects(self):
        values = ["A", "B"]
        conditions = {"id": {"$in": values}, "$or": [{"name": "x"}]}
        f = Filter(conditions)
        values.append("Z")
        conditions["$or"].append({"name": "y"})
        #Cambiar lo que pasó el usuario después de crear el Filter no afecta al Filter.
        self.assertEqual(f.to_dict()["id"], {"$in": ["A", "B"]})
        self.assertEqual(len(f.to_dict()["$or"]), 1)

    def test_equality_and_repr(self):
        self.assertEqual(Filter({"a": 1}), Filter({"a": {"$eq": 1}}))
        self.assertNotEqual(Filter({"a": 1}), Filter({"a": 2}))
        self.assertIn("Filter(", repr(Filter({"a": 1})))


if __name__ == "__main__":
    unittest.main()