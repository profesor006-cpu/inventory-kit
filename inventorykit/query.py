import copy #Para devolver copias profundas del filtro
import math #Para rechazar Nan, Inf que no le gustan a SQL
from .exceptions import InvalidFilterError #Excepcion para filtro mal armado

#Agrupamos los comparadores por grupos
_COMPARISON_OPERATORS = {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte"} # =, !=, >, >=, <, <=
_ORDERING_OPERATORS = {"$gt", "$gte", "$lt", "$lte"}
_MEMBERSHIP_OPERATORS = {"$in", "$nin"} #IN, NOT IN
_LOGICAL_OPERATORS = {"$and", "$or"}
_OTHER_OPERATORS = {"$exists", "$contains"}
_ALL_OPERATORS = (_COMPARISON_OPERATORS | _MEMBERSHIP_OPERATORS | _LOGICAL_OPERATORS | _OTHER_OPERATORS)
#Podemos importar _ALL_OPERATORS desde el query compiler luego

#True si value es int o float finito (bool da false)
def _is_number(value) -> bool:
    if type(value) is int:
        return True
    if type(value) is float:
        return math.isfinite(value)
    return False

#True si es None, bool, str o numero (lo que sabe usar json)
def _is_scalar(value) -> bool:
    if value is None or type(value) in (bool, str):
        return True
    return _is_number(value)

class Filter:
    #Recibe un dict al estilo del mongodb
    def __init__(self, conditions: dict) -> None:
        #Veamos que la forma sea valida
        self._validate_structure(conditions)
        #Guardamos la version normalizada
        self._conditions = self._parse_conditions(conditions)

    #Comprueba la estructura y composicion del filtro
    def _validate_structure(self, conditions: dict) -> None:
        if type(conditions) is not dict:
            raise InvalidFilterError("El filtro debe ser un diccionario.")
        for key, value in conditions.items(): #Recorremos cada par (clave, valor)
            #Las claves deben ser texto ...
            if type(key) is not str:
                raise InvalidFilterError("Las claves del filtro deben ser strings.")
            # ... no vacios (o solo espacios tampoco)
            if not key.strip():
                raise InvalidFilterError("El filtro tiene una clave vacía.")
            #Clave and o or
            if key in _LOGICAL_OPERATORS:
                #Su valor debe ser una lista con al menos un (sub)filtro
                if type(value) is not list or not value:
                    raise InvalidFilterError(f"{key} necesita una lista no vacía de subfiltros.")
                #Cada subfiltro debe seguir las mismas reglas
                for subfilter in value:
                    self._validate_structure(subfilter)
            #Clave empieza con $ pero no es de logica
            elif key.startswith("$"):
                #O es desconocido (va a llevar a un raise)
                self._validate_operator(key)
                #O esta mal ubicado (le hacemos raise tambien)
                raise InvalidFilterError(f"El operador {key} necesita un campo.")
            #Es un campo y su valor es un diccionario de operadores
            elif type(value) is dict:
                if not value: #diccionario vacio no me dice nada
                    raise InvalidFilterError(f"El campo {key!r} tiene un diccionario de operadores vacío.")
                operator_keys = []
                for k in value:
                    if type(k) is str and k.startswith("$"):
                        operator_keys.append(k)
                #Si alguna clave no es operador, el filtro es invalido
                if len(operator_keys) != len(value):
                    raise InvalidFilterError(f"El campo {key!r} debe usar solo operadores que empiecen con $")
            #Cualquier otro valor es una igualdad, se valida en validate operand
                
    #Rechaza operadores que no existen
    def _validate_operator(self, operator: str) -> None:
        if type(operator) is not str or operator not in _ALL_OPERATORS:
            raise InvalidFilterError(f"Operador desconocido: {operator!r}")

    #Comprueba que el valor recibido sea valido para el operator dado
    def _validate_operand(self, operator: str, value) -> None:
        #Existe el operador?
        self._validate_operator(operator)
        #Equals y Not equals aceptan cualquier valor simple (incluido None)
        if operator in ("$eq", "$ne"):
            if not _is_scalar(value):
                raise InvalidFilterError(f"{operator} necesita un valor simple (texto, número, bool o None).")
        # >, >=, <, <= aceptan numero o texto (no bool)
        elif operator in _ORDERING_OPERATORS:
            if not (_is_number(value) or type(value) is str):
                raise InvalidFilterError(f"{operator} necesita un número o un string, {value!r} no es válido")
        #In y Not in aceptar una lista (no vacia) de valores simples
        elif operator in _MEMBERSHIP_OPERATORS:
            if type(value) is not list or not value:
                raise InvalidFilterError(f"{operator} necesita una lista no vacía de valores simples")
            for item in value:
                if item is None or not _is_scalar(item): #Nota: No acepta None ya que IN (NULL) nunca coincide
                    raise InvalidFilterError(f"{operator} solo acepta strings, números o bool en la lista, {item!r} no es válido")
        #Exists solo acepta bool
        elif operator == "$exists":
            if type(value) is not bool:
                raise InvalidFilterError("$exists necesita un bool (True o False).")
        #Contains precisa un str no vacio
        elif operator == "$contains":
            if type(value) is not str or not value:
                raise InvalidFilterError("$contains necesita un string no vacío.")
        #And y Or precisan una lista no vacia de subfiltros (diccionarios)
        elif operator in _LOGICAL_OPERATORS:
            if type(value) is not list or not value:
                raise InvalidFilterError(f"{operator} necesita una lista no vacía de subfiltros.")
            for subfilter in value:
                if type(subfilter) is not dict:
                    raise InvalidFilterError(f"{operator} solo acepta diccionarios como subfiltros.")

    #Toda condicion de campo queda como {campo: {operador: valor}}
    #O sea normaliza el filtro
    def _parse_conditions(self, conditions: dict) -> dict:
        parsed = {}
        #Recorremos cada condicion del filtro
        for key, value in conditions.items():
            #And y Or: Verificamos y normalizamos recursivamente
            if key in _LOGICAL_OPERATORS:
                self._validate_operand(key, value)
                parsed_subfilters = []
                for subfilter in value:
                    parsed_subfilters.append(self._parse_conditions(subfilter))
                parsed[key] = parsed_subfilters
            #Si es un diccionario, son operadores aplicados a ese campo
            elif type(value) is dict:
                field_operators = {}
                for operator, operand in value.items():
                    #El operator debe ser valido
                    self._validate_operator(operator)
                    #And y or van a nivel de filtro: error
                    if operator in _LOGICAL_OPERATORS:
                        raise InvalidFilterError(f"{operator} no se puede usar dentro del campo {key!r}, tiene que ir a nivel del filtro")
                    #operand debe ser valido para el operator
                    self._validate_operand(operator, operand)
                    #Si el operand es una lista, guardamos una copia para no compartir el objeto con el usuario final
                    if type(operand) is list:
                        field_operators[operator] = list(operand)
                    #Si no es lista es inmutable, lo puedo guardar como está
                    else:
                        field_operators[operator] = operand
                parsed[key] = field_operators
            #Otro valor es una igualdad, se pasa a Equals
            else:
                self._validate_operand("$eq", value)
                parsed[key] = {"$eq": value}
        return parsed

    #Devuelve el filtro ya normalizado como diccionario
    #Nota: es una copia profunda, modificar (la copia) no altera el filter
    def to_dict(self) -> dict:
        return copy.deepcopy(self._conditions)

    #Para mostrar como se ve el filter con los print()
    def __repr__(self) -> str:
        return f"Filter({self._conditions!r})"

    #Dos filtros son iguales ssi sus formas normalizadas son iguales
    def __eq__(self, other):
        #El otro no es un filter
        if not isinstance(other, Filter):
            return NotImplemented
        #Comparamos
        return self._conditions == other._conditions

class Projection:
    def __init__(self, fields: dict) -> None:
        pass

    def _validate_fields(self, fields: dict) -> None:
        pass

    def _validate_mode(self, fields: dict) -> None:
        pass

    def to_dict(self) -> dict:
        pass


class Sort:
    def __init__(self, fields: dict) -> None:
        pass

    def _validate_fields(self, fields: dict) -> None:
        pass

    def _validate_direction(self, direction: int) -> None:
        pass

    def to_dict(self) -> dict:
        pass


class _QueryCompiler:
    def _resolve_field(self, field: str, entity: str) -> str:
        pass

    def _compile_filter(self, filter: Filter | None, entity: str) -> tuple[str, list]:
        pass

    def _compile_condition(self, field: str, operator: str, value, entity: str) -> tuple[str, list]:
        pass

    def _compile_logical(self, operator: str, conditions: list, entity: str) -> tuple[str, list]:
        pass

    def _compile_projection(self, projection: Projection | None, entity: str) -> str:
        pass

    def _compile_sort(self, sort: Sort | None, entity: str) -> str:
        pass

    def _compile_pagination(self, limit: int | None, skip: int) -> tuple[str, list]:
        pass

    def _compile_query(self, entity: str, filter: Filter | None = None, projection: Projection | None = None, sort: Sort | None = None, limit: int | None = None, skip: int = 0, include_inactive: bool = False) -> tuple[str, list]:
        pass

