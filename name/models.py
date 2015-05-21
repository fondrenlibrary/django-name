import json
import requests
import markdown2

from django.core.urlresolvers import reverse
from django.db import models, transaction, connection
from pynaco.naco import normalizeSimplified

from .validators import validate_merged_with

BIOGRAPHICAL_HISTORICAL = 0
DELETION_INFORMATION = 1
NONPUBLIC = 2
SOURCE = 3
NOTE_TYPE_OTHER = 4

NOTE_TYPE_CHOICES = (
    (BIOGRAPHICAL_HISTORICAL, 'Biographical/Historical'),
    (DELETION_INFORMATION, 'Deletion Information'),
    (NONPUBLIC, 'Nonpublic'),
    (SOURCE, 'Source'),
    (NOTE_TYPE_OTHER, 'Other'),
)

ACTIVE = 0
DELETED = 1
SUPPRESSED = 2

RECORD_STATUS_CHOICES = (
    (ACTIVE, 'Active'),
    (DELETED, 'Deleted'),
    (SUPPRESSED, 'Suppressed'),
)

PERSONAL = 0
ORGANIZATION = 1
EVENT = 2
SOFTWARE = 3
BUILDING = 4

NAME_TYPE_CHOICES = (
    (PERSONAL, 'Personal'),
    (ORGANIZATION, 'Organization'),
    (EVENT, 'Event'),
    (SOFTWARE, 'Software'),
    (BUILDING, 'Building'),
)

DATE_DISPLAY_LABELS = {
    PERSONAL: {
        'type': 'Personal',
        'begin': 'Date of Birth',
        'end': 'Date of Death'
    },
    ORGANIZATION: {
        'type': 'Organization',
        'begin': 'Founded Date',
        'end': 'Defunct'
    },
    EVENT: {
        'type': 'Event',
        'begin': 'Begin Date',
        'end': 'End Date'
    },
    SOFTWARE: {
        'type': 'Software',
        'begin': 'Begin Date',
        'end': 'End Date'
    },
    BUILDING: {
        'type': 'Building',
        'begin': 'Erected Date',
        'end': 'Demolished Date',
    },
    None: {
        'type': None,
        'begin': 'Born/Founded Date',
        'end': 'Died/Defunct Date'
    },
}


ACRONYM = 0
ABBREVIATION = 1
TRANSLATION = 2
EXPANSION = 3
VARIANT_TYPE_OTHER = 4

VARIANT_TYPE_CHOICES = (
    (ACRONYM, 'Acronym'),
    (ABBREVIATION, 'Abbreviation'),
    (TRANSLATION, 'Translation'),
    (EXPANSION, 'Expansion'),
    (VARIANT_TYPE_OTHER, 'Other'),
)

CURRENT = 0
FORMER = 1

LOCATION_STATUS_CHOICES = (
    (CURRENT, "current"),
    (FORMER, "former"),
)

NAME_TYPE_SCHEMAS = {
    PERSONAL: 'http://schema.org/Person',
    ORGANIZATION: 'http://schema.org/Organization',
    BUILDING: 'http://schema.org/Place',
}


class Identifier_Type(models.Model):
    label = models.CharField(
        max_length=255,
        help_text="What kind of data is this? Personal website? Twitter?",
    )
    icon_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Path to icon image?",
    )
    homepage = models.URLField(
        blank=True,
        help_text="Homepage of label. Twitter.com, Facebook.com, etc",
    )

    class Meta:
        ordering = ["label"]
        verbose_name = "Identifier Type"

    def __unicode__(self):
        return self.label


class Identifier(models.Model):
    type = models.ForeignKey(
        "Identifier_Type",
        help_text="Catagorize this record's identifiers here",
    )
    belong_to_name = models.ForeignKey("Name")
    value = models.CharField(max_length=500)
    visible = models.BooleanField(default=True)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "type"]

    def __unicode__(self):
        return self.value


class NoteManager(models.Manager):
    use_for_related_fields = True

    def public_notes(self):
        return self.get_queryset().exclude(note_type=NONPUBLIC)


class Note(models.Model):
    note = models.TextField(help_text="Enter notes about this record here")
    note_type = models.IntegerField(choices=NOTE_TYPE_CHOICES)
    belong_to_name = models.ForeignKey("Name")

    objects = NoteManager()

    def get_note_type_label(self):
        """Returns the label associated with an instance's
        note_type.
        """
        id, note_type = NOTE_TYPE_CHOICES[self.note_type]
        return note_type

    def __unicode__(self):
        return self.note


class Variant(models.Model):
    belong_to_name = models.ForeignKey("Name")
    variant_type = models.IntegerField(
        max_length=50,
        choices=VARIANT_TYPE_CHOICES,
        help_text="Choose variant type.",
    )
    variant = models.CharField(
        max_length=255,
        help_text="Fill in the other name variants, if any.",
    )
    normalized_variant = models.CharField(
        max_length=255,
        help_text="NACO normalized variant text",
        editable=False,
    )

    def get_variant_type_label(self):
        """Returns the label associated with an instance's
        variant_type.
        """
        id, variant_type = VARIANT_TYPE_CHOICES[self.variant_type]
        return variant_type

    def save(self):
        self.normalized_variant = normalizeSimplified(self.variant)
        super(Variant, self).save()

    def __unicode__(self):
        return self.variant


class TicketingManager(models.Manager):
    """Custom manager for the BaseTicketing model."""

    def create(self, *args, **kwargs):
        """Override the create method.

        Create or get the single object. If one already exists,
        delete it and create a new one so we auto-increment the id.
        """
        obj, created = self.get_or_create(stub=self.model.STUB_DEFAULT)
        if not created:
            with transaction.atomic():
                obj.delete()
                obj = self.create(stub=self.model.STUB_DEFAULT)
        return obj


class BaseTicketing(models.Model):

    # Explicitly set the id of the model, even though it is the same
    # as the one Django gives it.
    id = models.AutoField(null=False, primary_key=True)

    # This is just the smallest placeholder we can create that we can
    # replace into to generate a new id.
    STUB_DEFAULT = True
    stub = models.BooleanField(null=False, default=STUB_DEFAULT, unique=True)

    # Override the default manager
    objects = TicketingManager()

    @property
    def ticket(self):
        """Alias for id"""
        return self.id

    def __unicode__(self):
        return u'nm%07d' % self.ticket


class NameManager(models.Manager):
    def visible(self):
        """Retrieves all Name objects that have an Active record status
        and are not merged with any other Name objects.
        """
        return self.get_queryset().filter(
            record_status=ACTIVE, merged_with=None)

    def active_type_counts(self):
        """Calculates counts of Name objects by Name Type.

        Statistics are based off of the queryset returned by visible.
        The total number is calculated using the count method. All
        additional figures are calculated using Python to reduce the number
        of queries.
        """
        names = self.visible()
        return {
            'total': names.count(),
            'personal': len(filter(lambda n: n.is_personal(), names)),
            'organization': len(filter(lambda n: n.is_organization(), names)),
            'event': len(filter(lambda n: n.is_event(), names)),
            'software': len(filter(lambda n: n.is_software(), names)),
            'building': len(filter(lambda n: n.is_building(), names)),
        }

    def _counts_per_month(self, date_column):
        """Calculates the number of Names by month according to the
        date_column passed in.

        This will return a ValueQuerySet where each element is in the form
        of
            {
               count: <Number of Names for the month>,
               month: <Datetime object for first day of the given month>
            }
        """
        truncate_date = connection.ops.date_trunc_sql('month', date_column)
        return (self.extra({'month': truncate_date})
                    .values('month')
                    .annotate(count=models.Count(date_column))
                    .order_by(date_column))

    def created_stats(self):
        """Returns a ValueQuerySet of the number of Names created per
        month.
        """
        return self._counts_per_month('date_created')

    def modified_stats(self):
        """Returns a ValueQuerySet of the number of Names modified per
        month.
        """
        return self._counts_per_month('last_modified')


class Name(models.Model):
    """
    The record model defines the information stored by the name app
    Each record has a unique name identifier associated with it which is
    implemented as UUID.
    """

    # only one name per record
    name = models.CharField(
        max_length=255,
        help_text="Please use the general reverse order: LAST, FIRST",
    )

    normalized_name = models.CharField(
        max_length=255,
        help_text="NACO normalized form of the name",
        editable=False,
    )

    # the name must be one of a certain type, currently 4 choices
    name_type = models.IntegerField(
        max_length=1,
        choices=NAME_TYPE_CHOICES,
    )

    # date, month or year of birth or incorporation of the name
    begin = models.CharField(
        max_length=25,
        blank=True,
        help_text="Conforms to EDTF format YYYY-MM-DD",
    )

    # date, month of year of death or un-incorporation of the name
    end = models.CharField(
        max_length=25,
        blank=True,
        help_text="Conforms to EDTF format YYYY-MM-DD",
    )

    # MusicBrainz derived
    disambiguation = models.CharField(
        max_length=255,
        blank=True,
        help_text="Clarify to whom or what this record pertains."
    )

    # bio text - formatted with _markdown_ markup
    biography = models.TextField(
        blank=True,
        help_text="Compatible with MARKDOWN",
    )

    # record status flag (active / merged / etc)
    record_status = models.IntegerField(
        choices=RECORD_STATUS_CHOICES,
        default="0",
    )

    # if marked merged, value is record id of target to merge with
    merged_with = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        related_name='merged_with_name',
    )

    # automatically generate created date
    date_created = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )

    # update when we change the record
    last_modified = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    # auto incrementing from nameid
    name_id = models.CharField(
        max_length=10,
        unique=True,
        editable=False,
    )

    objects = NameManager()

    def has_geocode(self):
        l = Location.objects.filter(belong_to_name=self)
        if len(l) > 0:
            return True
        else:
            return False

    # this enables icon display on the django admin rather than textual "T/F"
    has_geocode.boolean = True

    def render_biography(self):
        """Render the Markdown biography to HTML."""
        return markdown2.markdown(self.biography)

    def get_absolute_url(self):
        return reverse('name:entry-detail', args=[self.name_id])

    def has_schema_url(self):
        return self.get_schema_url() is not None

    def get_schema_url(self):
        return NAME_TYPE_SCHEMAS.get(self.name_type, None)

    def get_name_type_label(self):
        id, name_type = NAME_TYPE_CHOICES[self.name_type]
        return name_type

    def get_date_display(self):
        return DATE_DISPLAY_LABELS.get(self.name_type)

    def _is_name_type(self, type_id):
        """Test if the instance of Name is a certain
        Name Type.

        Accepts the id of the Name Type, and returns a boolean.
        """
        return type_id == self.name_type

    def is_personal(self):
        """True if the Name has the Name Type Personal."""
        return self._is_name_type(PERSONAL)

    def is_organization(self):
        """True if the Name has the Name Type Organization."""
        return self._is_name_type(ORGANIZATION)

    def is_event(self):
        """True if the Name has the Name Type Event."""
        return self._is_name_type(EVENT)

    def is_software(self):
        """True if the Name has the Name Type Software."""
        return self._is_name_type(SOFTWARE)

    def is_building(self):
        """True if the Name has the Name Type Building."""
        return self._is_name_type(BUILDING)

    def _is_record_status(self, status_id):
        """Test if the instance of Name has a particular
        record_status.

        Accepts the id of the Name Type, and returns a boolean.
        """
        return status_id == self.record_status

    def is_active(self):
        """True if the Name has the Active status."""
        return self._is_record_status(ACTIVE)

    def is_deleted(self):
        """True if the Name has the Deleted status."""
        return self._is_record_status(DELETED)

    def is_suppressed(self):
        """True if the Name has the Suppressed status."""
        return self._is_record_status(SUPPRESSED)

    def has_current_location(self):
        """True if the Name has a current location in the location_set."""
        return self.location_set.current_location is not None

    def save(self, **kwargs):
        if not self.name_id:
            self.name_id = unicode(BaseTicketing.objects.create())
        self.normalized_name = normalizeSimplified(self.name)
        super(Name, self).save()
        if self.is_building() and Location.objects.filter(belong_to_name=self).count() == 0:
            url = 'http://maps.googleapis.com/maps/api/geocode/json?address=%s&sensor=true' % self.normalized_name
            search_json = json.loads(requests.get(url).content)
            if search_json['status'] == 'OK' and len(search_json['results']) == 1:
                geo_location = search_json['results'][0]['geometry']['location']
                Location.objects.create(
                    belong_to_name=self,
                    latitude=geo_location['lat'],
                    longitude=geo_location['lng']
                )

    def clean(self, *args, **kwargs):
        # Call merged_with_validator here so that we can pass in
        # the model instance.
        validate_merged_with(self)
        super(Name, self).clean(*args, **kwargs)

    def __unicode__(self):
        return self.name_id

    class Meta:
        ordering = ["name"]
        unique_together = (('name', 'name_id'),)


class LocationManager(models.Manager):
    use_for_related_fields = True

    def _get_current_location(self):
        """Filters through a Name objects related locations and
        returns the one marked as current.
        """
        return self.get_queryset().filter(status=CURRENT).first()

    # Makes the current location available as a property on
    # the RelatedManager.
    current_location = property(_get_current_location)


class Location(models.Model):
    belong_to_name = models.ForeignKey("Name")
    latitude = models.DecimalField(
        max_digits=13,
        decimal_places=10,
        help_text="""
        <strong>
            <a target="_blank" href="http://itouchmap.com/latlong.html">
                iTouchMap
            </a>
            : this service might be useful for filling in the lat/long data
        </strong>
        """,
    )
    longitude = models.DecimalField(
        max_digits=13,
        decimal_places=10,
        help_text="""
        <strong>
            <a target="_blank" href="http://itouchmap.com/latlong.html">
                iTouchMap
            </a>
            : this service might be useful for filling in the lat/long data
        </strong>
        """,
    )
    status = models.IntegerField(
        max_length=2,
        choices=LOCATION_STATUS_CHOICES,
        default=0)

    objects = LocationManager()

    class Meta:
        ordering = ["status"]

    def geo_point(self):
        return "%s %s" % (self.latitude, self.longitude)

    def is_current(self):
        """True if the Location has a status of Current."""
        return CURRENT == self.status

    def save(self, **kwargs):
        super(Location, self).save()
        # if we change this location to the current location, all other
        # locations that belong to the same name should be changed to former.
        if self.is_current():
            former_locs = Location.objects.filter(
                belong_to_name=self.belong_to_name).exclude(pk=self.pk)
            for l in former_locs:
                l.status = 1
                l.save()

    def __unicode__(self):
        return self.geo_point()
