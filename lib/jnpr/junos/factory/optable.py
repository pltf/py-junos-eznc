from copy import deepcopy
import logging

# 3rd-party
from lxml import etree
from lxml.builder import E

# local
from jnpr.junos.factory.table import Table
from jnpr.junos.jxml import remove_namespaces, remove_namespaces_and_spaces
from jnpr.junos.decorators import checkSAXParserDecorator

logger = logging.getLogger("jnpr.junos.factory.optable")


class OpTable(Table):

    # -------------------------------------------------------------------------
    # PUBLIC METHODS
    # -------------------------------------------------------------------------

    @checkSAXParserDecorator
    def get(self, *vargs, **kvargs):
        """
        Retrieve the XML table data from the Device instance and
        returns back the Table instance - for call-chaining purposes.

        If the Table was created with a :path: rather than a Device,
        then this method will load the XML from that file.  In this
        case, the \*vargs, and \**kvargs are not used.

        ALIAS: __call__

        :vargs:
          [0] is the table :arg_key: value.  This is used so that
          the caller can retrieve just one item from the table without
          having to know the Junos RPC argument.

        :kvargs:
          these are the name/value pairs relating to the specific Junos
          XML command attached to the table.  For example, if the RPC
          is 'get-route-information', there are parameters such as
          'table' and 'destination'.  Any valid RPC argument can be
          passed to :kvargs: to further filter the results of the :get():
          operation.  neato!

        NOTES:
          If you need to create a 'stub' for unit-testing
          purposes, you want to create a subclass of your table and
          overload this methods.
        """
        self._clearkeys()

        if self._path is not None:
            # for loading from local file-path
            self.xml = remove_namespaces(etree.parse(self._path).getroot())
            return self

        if self._lxml is not None:
            return self

        argkey = vargs[0] if len(vargs) else None

        rpc_args = {}

        if self._use_filter:
            try:
                filter_xml = generate_sax_parser_input(self)
                rpc_args['filter_xml'] = filter_xml
            except Exception as ex:
                logger.debug("Not able to create SAX parser input due to "
                               "'%s'" % ex)

        self.D.transform = lambda: remove_namespaces_and_spaces
        rpc_args.update(self.GET_ARGS)    # copy default args
        # saltstack get_table pass args as named keyword
        if 'args' in kvargs and isinstance(kvargs['args'], dict):
            rpc_args.update(kvargs.pop('args'))
        rpc_args.update(kvargs)           # copy caller provided args


        if hasattr(self, 'GET_KEY') and argkey is not None:
            rpc_args.update({self.GET_KEY: argkey})

        # execute the Junos RPC to retrieve the table
        self.xml = getattr(self.RPC, self.GET_RPC)(**rpc_args)

        # returning self for call-chaining purposes, yo!
        return self


def generate_sax_parser_input(obj):
    """
    Used to generate xml object from Table/view to be used in SAX parsing
    Args:
        obj: self object which contains table/view details

    Returns: lxml etree object to be used as sax parser input

    """
    if '/' in obj.ITEM_XPATH:
        tags = obj.ITEM_XPATH.split('/')
        parser_ingest = E(tags.pop(-1), E(obj.ITEM_NAME_XPATH))
        for tag in tags[::-1]:
            parser_ingest = E(tag, parser_ingest)
    else:
        parser_ingest = E(obj.ITEM_XPATH, E(obj.ITEM_NAME_XPATH))
    local_field_dict = deepcopy(obj.VIEW.FIELDS)
    # first make element out of group fields
    if obj.VIEW.GROUPS:
        for group, group_xpath in obj.VIEW.GROUPS.items():
            # need to pop out group items so that it wont be reused with fields
            group_field_dict = ({k: local_field_dict.pop(k)
                                 for k, v in obj.VIEW.FIELDS.items()
                                 if v.get('group') == group})
            group_ele = E(group_xpath)
            for key, val in group_field_dict.items():
                group_ele.append(E(val.get('xpath')))
            parser_ingest.append(group_ele)
    map_multilayer_fields = dict()
    for i, item in enumerate(local_field_dict.items()):
        # i is the index and item will be taple of field key and value
        field_dict = item[1]
        if 'table' in field_dict:
            # handle nested table/view
            child_table = field_dict.get('table')
            parser_ingest.insert(i + 1, generate_sax_parser_input(child_table))
        else:
            xpath = field_dict.get('xpath')
            # xpath can be multi level, for ex traffic-statistics/input-pps
            if '/' in xpath:
                tags = xpath.split('/')
                if tags[0] in map_multilayer_fields:
                    # cases where multiple fields got same parents
                    # fields:
                    #    input-bytes: traffic-statistics/input-bytes
                    #    output-bytes: traffic-statistics/output-bytes
                    existing_elem = parser_ingest.xpath(tags[0])
                    if existing_elem:
                        obj = existing_elem[0]
                        for tag in tags[1:]:
                            obj.append(E(tag))
                    else:
                        continue
                else:
                    obj = E(tags[0])
                    for tag in tags[1:]:
                        obj.append(E(tag))
                    map_multilayer_fields[tags[0]] = obj
                parser_ingest.insert(i + 1, obj)
            else:
                parser_ingest.insert(i + 1, E(xpath))
    return parser_ingest
