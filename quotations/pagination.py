from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsPagination(PageNumberPagination):
    """
    Custom pagination class for Lead and Quotation endpoints.
    
    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Number of items per page (default: 10, max: 100)
    """
    page_size = 10  # Default page size
    page_size_query_param = 'page_size'
    max_page_size = 100


    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data
        })

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'count': {
                    'type': 'integer',
                    'example': 123,
                },
                'total_pages': {
                    'type': 'integer',
                    'example': 13,
                },
                'current_page': {
                    'type': 'integer',
                    'example': 1,
                },
                'current_page': {
                    'type': 'integer',
                    'example': 1,
                },
                'next': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=4',
                },
                'previous': {
                    'type': 'string',
                    'nullable': True,
                    'format': 'uri',
                    'example': 'http://api.example.org/accounts/?page=2',
                },
                'results': schema,
            },
        }
